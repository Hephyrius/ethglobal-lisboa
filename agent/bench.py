"""Measure what a real decision actually costs on this machine.

    uv run python -m agent.bench --model qwen2.5:3b-instruct-q4_K_M --runs 3

Synthetic tokens-per-second is the wrong number for choosing a model here. What
matters is **how long a validated decision takes**, and that includes the retry
multiplier: a model that emits malformed JSON twice turns a 60-second tick into
three minutes. A slightly weaker model that gets the schema right first time can
beat a stronger one outright. Nothing but running the real prompt through the
real validator will tell you which.

So this reports two things per model:

- **mechanical** — one raw completion, giving prefill and generation tok/s from
  the endpoint's own token counts. Comparable across machines.
- **end to end** — the full `LlmDecisionEngine`: real curator prompt, real
  four-layer validation, real reject-and-retry. This is the number that decides
  whether the demo feels alive.

Kept as a permanent tool rather than a throwaway (INSTRUCTIONS.md Rule 6): the
macOS teammate has to pick a model on different hardware at 10:00, and anyone
who edits the prompt wants to know what it cost.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass, field

import httpx

from . import fixtures
from .config import settings
from .loop.engine import LlmDecisionEngine
from .model.backends.ollama import OllamaBackend
from .model.prompts.curator import decision_messages, decision_schema
from .model.validation import DecisionRejected

__all__ = ["main"]


@dataclass
class RunResult:
    ok: bool
    seconds: float
    attempts: int = 1
    action: str = "-"
    detail: str = ""


@dataclass
class ModelReport:
    model: str
    prefill_tokens: int = 0
    output_tokens: int = 0
    prefill_per_s: float = 0.0
    output_per_s: float = 0.0
    runs: list[RunResult] = field(default_factory=list)
    error: str = ""

    @property
    def durations(self) -> list[float]:
        return [r.seconds for r in self.runs]

    @property
    def successes(self) -> int:
        return sum(1 for r in self.runs if r.ok)

    @property
    def total_attempts(self) -> int:
        return sum(r.attempts for r in self.runs)


async def _mechanical(base_url: str, model: str, messages: list[dict[str, str]]) -> ModelReport:
    """One raw completion, timed, using the endpoint's own token accounting."""
    report = ModelReport(model=model)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=900.0) as client:
            response = await client.post(f"{base_url.rstrip('/')}/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        report.error = f"{type(exc).__name__}: {exc}"
        return report
    elapsed = time.perf_counter() - started

    usage = body.get("usage") or {}
    report.prefill_tokens = int(usage.get("prompt_tokens") or 0)
    report.output_tokens = int(usage.get("completion_tokens") or 0)
    # Ollama does not split prefill and generation timing in the OpenAI-compatible
    # response, so generation rate is derived from total elapsed. That slightly
    # understates it — which is the safe direction for a demo estimate.
    if elapsed > 0:
        report.output_per_s = report.output_tokens / elapsed
        report.prefill_per_s = report.prefill_tokens / elapsed
    return report


async def _end_to_end(model: str, runs: int, max_attempts: int) -> list[RunResult]:
    """Full cycles through the real prompt and the real validator."""
    cfg = settings()
    backend = OllamaBackend(
        base_url=cfg.ollama_base_url, model=model, timeout=cfg.model_timeout_s
    )
    engine = LlmDecisionEngine(backend, max_attempts=max_attempts)
    mandate, snapshot = fixtures.mandate(), fixtures.market_snapshot()
    vault = fixtures.vault_state()

    results: list[RunResult] = []
    for index in range(runs):
        started = time.perf_counter()
        try:
            validated = await engine.decide_in_full(mandate, snapshot, vault)
        except DecisionRejected as exc:
            results.append(
                RunResult(
                    ok=False,
                    seconds=time.perf_counter() - started,
                    attempts=exc.attempts,
                    detail=exc.failures[-1][:90] if exc.failures else "",
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                RunResult(
                    ok=False,
                    seconds=time.perf_counter() - started,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            results.append(
                RunResult(
                    ok=True,
                    seconds=time.perf_counter() - started,
                    attempts=validated.attempts,
                    action=validated.decision.action,
                    detail=validated.failures[-1][:90] if validated.failures else "",
                )
            )
        print(f"    run {index + 1}/{runs}: {_describe(results[-1])}", flush=True)
    return results


def _describe(run: RunResult) -> str:
    verdict = "ok " if run.ok else "REJECTED"
    retries = "" if run.attempts == 1 else f", {run.attempts - 1} retry(s)"
    detail = f"  [{run.detail}]" if run.detail else ""
    return f"{verdict} {run.seconds:6.1f}s  action={run.action}{retries}{detail}"


def _print_report(report: ModelReport, runs: int) -> None:
    print(f"\n  {report.model}")
    if report.error:
        print(f"    unavailable: {report.error}")
        return

    print(
        f"    mechanical : {report.prefill_tokens} prompt + {report.output_tokens} output tokens"
        f"  ~{report.output_per_s:.1f} output tok/s"
    )
    if not report.runs:
        return

    median = statistics.median(report.durations)
    print(
        f"    end to end : median {median:.1f}s  "
        f"(min {min(report.durations):.1f}s, max {max(report.durations):.1f}s)"
    )
    print(
        f"    reliability: {report.successes}/{len(report.runs)} valid, "
        f"{report.total_attempts} model call(s) for {runs} decision(s)"
    )
    if report.successes < len(report.runs):
        print("    ^ a rejected run means validation refused it — nothing would have executed")


async def _run(models: list[str], runs: int, max_attempts: int) -> None:
    cfg = settings()
    messages = decision_messages(
        fixtures.mandate(), fixtures.market_snapshot(), fixtures.vault_state()
    )
    approx_chars = sum(len(m["content"]) for m in messages)

    print(f"endpoint : {cfg.ollama_base_url}")
    print(f"prompt   : {approx_chars} characters across {len(messages)} messages")
    print(f"schema   : AllocationDecision ({len(str(decision_schema()))} chars)")

    for model in models:
        print(f"\n[{model}] warming up and measuring one raw completion…", flush=True)
        report = await _mechanical(cfg.ollama_base_url, model, messages)
        if not report.error:
            print(f"[{model}] running {runs} validated decision(s)…", flush=True)
            report.runs = await _end_to_end(model, runs, max_attempts)
        _print_report(report, runs)

    print(
        "\nA tick also spends time on the data snapshot and the chain call, so budget "
        "a little above the end-to-end median."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent.bench", description="Measure the real cost of a validated decision."
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="model tag to measure; repeat to compare several",
    )
    parser.add_argument("--runs", type=int, default=3, help="validated decisions per model")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=settings().max_validation_retries,
        help="validation attempts before a decision is rejected",
    )
    args = parser.parse_args(argv)

    models = args.models or [settings().model_name]
    asyncio.run(_run(models, max(1, args.runs), max(1, args.max_attempts)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
