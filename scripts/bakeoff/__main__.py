"""Replay fixed scenarios through N candidate models and score them.

    uv run python -m scripts.bakeoff --models qwen2.5:3b-instruct-q4_K_M --trials 3
    uv run python -m scripts.bakeoff --models a,b --scenarios balanced-ship --json out.json
    uv run python -m scripts.bakeoff --check                # can this machine run a candidate?
    uv run python -m scripts.bakeoff --list

Parameterised over models, scenarios and trial count so it is worth running again — on a bigger
machine, after a prompt change, or when a new model appears — rather than being a script that
answered one question once (Rule 6).

**What it exists to settle.** `act_000020` is in the decision feed carrying an honest caveat that
*the decision was scripted, not model-authored*, because the 3B failed three attempts at an Aqua
ship even with the intent shape in the prompt (#51b). That caveat is the weakest sentence in the
submission. Three attempts is an anecdote; this makes it a measurement, and gives the same
measurement for any candidate that might beat it.

**It measures the production path, not an approximation of it.** The prompt comes from Lane B's
`decision_messages`, the structured-output schema from their `decision_schema`, validation from
their `validate_decision`, and constraint checking from their `check_decision`. A bake-off that
built its own prompt would be measuring the bake-off.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

from agent.model.backends.ollama import OllamaBackend
from agent.model.prompts.curator import decision_messages, decision_schema

from .scenarios import all_scenarios, scenario as get_scenario, snapshot
from .scoring import ModelReport, Trial, markdown_table, score

DEFAULT_BASE_URL = "http://localhost:11434/v1"
#: Enough for a decision with reasoning; a model that needs more is not going to fit this loop.
TIMEOUT_S = 900.0


def _available_ram_gb() -> float | None:
    """Free physical memory, or None where we cannot tell.

    Worth knowing before a run rather than after: a 7B q4 needs ~5 GB resident, and loading one
    into a machine with a gigabyte free does not fail — it pages, drags every other process on the
    box with it, and produces a latency number that measures the swap file rather than the model.
    """
    try:  # Linux/WSL
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    if shutil.which("wmic"):  # Windows, no dependency
        import subprocess

        try:
            out = subprocess.run(
                ["wmic", "OS", "get", "FreePhysicalMemory", "/value"],
                capture_output=True, text=True, timeout=30, check=False,
            ).stdout
            for line in out.splitlines():
                if "=" in line:
                    return int(line.split("=")[1].strip()) / 1024 / 1024
        except Exception:  # noqa: BLE001 — a missing number is not a failure
            return None
    return None


def _resident_models(base_url: str) -> list[str]:
    """What ollama already has in memory. A resident model costs no further RAM to benchmark,
    which is the difference between "cannot measure anything here" and "can measure the baseline"."""
    import urllib.request

    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    try:
        with urllib.request.urlopen(f"{root}/api/ps", timeout=10) as resp:
            return [m["name"] for m in json.loads(resp.read()).get("models", [])]
    except Exception:  # noqa: BLE001 — an unreachable ollama is reported by the caller
        return []


async def run_trials(
    model: str, *, base_url: str, scenarios: list[str], trials: int, temperature: float
) -> ModelReport:
    # `ModelBackend` is an async port, and an un-awaited coroutine is falsy-adjacent rather than
    # an error: the first version of this called `reachable()` without awaiting, believed the
    # truthy coroutine object, and then scored twelve trials as invalid output in 0.0 seconds.
    # A harness that reports a perfect failure is indistinguishable from a model that failed.
    backend = OllamaBackend(base_url=base_url, model=model, timeout=TIMEOUT_S)
    if not await backend.reachable():
        raise SystemExit(f"ollama not reachable at {base_url}")
    if hasattr(backend, "has_model") and not await backend.has_model():
        raise SystemExit(
            f"model {model!r} is not pulled. `ollama pull {model}` first — this harness will not "
            f"download gigabytes on your behalf."
        )

    snap = snapshot()
    schema = decision_schema()
    out: list[Trial] = []

    for key in scenarios:
        sc = get_scenario(key)
        messages = decision_messages(sc.mandate, snap, sc.vault)
        for attempt in range(1, trials + 1):
            started = time.monotonic()
            try:
                # temperature 0 by default: this is a capability measurement, and sampling noise
                # would let a model pass by luck on one run and fail on the next.
                raw = await backend.complete(
                    messages, json_schema=schema, temperature=temperature
                )
            except Exception as exc:  # noqa: BLE001
                elapsed = time.monotonic() - started
                t = Trial(
                    model=model, scenario=key, valid_first_attempt=False,
                    latency_s=round(elapsed, 2), error=f"{type(exc).__name__}: {exc}"[:400],
                )
            else:
                t = score(
                    raw, model=model, scenario=sc, snapshot=snap,
                    latency_s=time.monotonic() - started,
                )
            out.append(t)
            flag = "ok " if t.valid_first_attempt else "BAD"
            shape = "shape ok" if t.authored_wanted_intent else "wrong shape"
            print(
                f"  {key:<17} trial {attempt}/{trials}  {flag}  {t.latency_s:>6.1f}s  "
                f"{t.action or '-':<9} intents={t.intents or '[]'}  {shape}"
                + (f"  {t.error}" if t.error else ""),
                flush=True,
            )
    return ModelReport(model=model, trials=out)


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252, which cannot encode the tick in the results table — and
    # the failure lands at the very END of a run, after every trial has been paid for.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(prog="bakeoff", description=__doc__)
    p.add_argument("--models", default="", help="comma-separated ollama model tags")
    p.add_argument("--scenarios", default="", help="comma-separated scenario keys (default: all)")
    p.add_argument("--trials", type=int, default=3, help="attempts per scenario (default 3)")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--json", type=Path, help="write every trial to this file")
    p.add_argument("--list", action="store_true", help="list scenarios and exit")
    p.add_argument("--check", action="store_true", help="report what this machine can run, and exit")
    args = p.parse_args(argv)

    if args.list:
        for s in all_scenarios():
            print(f"{s.key:<18} expects: {s.expects}")
            print(f"{'':<18} why:     {s.why}\n")
        return 0

    ram = _available_ram_gb()
    if args.check:
        print(f"free RAM: {ram:.1f} GB" if ram else "free RAM: unknown")
        resident = _resident_models(args.base_url)
        print(f"already resident (costs no further memory): {resident or 'nothing'}")
        print("\nHeadroom to load a model that is NOT already resident:")
        # Rough resident sizes for q4_K_M quantizations plus context.
        for tag, need in (("3B", 2.5), ("7-8B", 5.5), ("14B", 10.0)):
            verdict = "unknown" if ram is None else ("yes" if ram >= need else "NO")
            print(f"  {tag:<6} needs ~{need:>4.1f} GB -> {verdict}")
        if ram is not None and ram < 5.5:
            print(
                "\nA larger candidate cannot be benchmarked here without paging. That is a\n"
                "finding, not an obstacle to route around: a latency number measured against\n"
                "the swap file is worse than no number, and on this box the same memory is\n"
                "holding anvil's fork state and the running API."
            )
        return 0

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        p.error("--models is required (or use --check / --list)")
    keys = [k.strip() for k in args.scenarios.split(",") if k.strip()] or [
        s.key for s in all_scenarios()
    ]

    print(f"available RAM: {ram:.1f} GB" if ram else "available RAM: unknown")
    print(f"{len(models)} model(s) x {len(keys)} scenario(s) x {args.trials} trial(s)\n")

    reports: list[ModelReport] = []
    for model in models:
        print(f"{model}")
        reports.append(
            asyncio.run(
                run_trials(
                    model, base_url=args.base_url, scenarios=keys,
                    trials=args.trials, temperature=args.temperature,
                )
            )
        )
        print()

    print(markdown_table(reports))

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "trials": [t.as_dict() for r in reports for t in r.trials],
                    "available_ram_gb": ram,
                    "temperature": args.temperature,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
