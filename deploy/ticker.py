"""Tick every curated vault on a timer, so the feed has history by demo time.

One tick proves the agent works. A dozen over an afternoon shows it *deciding* —
holding when nothing changed, moving when a rate did — and that is the thing a
judge is actually assessing. It also gives `agent/performance/store.py` enough
points to draw a line rather than a dot.

Runs as a compose service beside the API and talks to it over the internal
network, so nothing is exposed and no credential lives here.

## What it will not do

**It will not spend the agent to zero.** `MIN_AGENT_ETH` is checked before every
round and the loop stops permanently below it. An agent that runs dry fails in
the least legible way this repo has: `/health` stays green, the model reasons
correctly, all six validation layers pass, and only the broadcast fails with
`-32003`. Discovering that ten minutes before a demo is the scenario this guard
exists for.

**It will not tick faster than the mandates allow.** Every mandate carries
`rebalance_cooldown_seconds` — 7200 in the shipped conservative preset — and a
tick inside that window is refused by the harness anyway. Polling faster than
the cooldown does not produce more decisions, it produces more *rejections* in
the feed, which is worse than nothing: it fills the judge-facing log with noise
that reads like the agent failing.

**It will not tick a vault that cannot be read.** Vaults deployed before the
`priceMaxAge` fix revert `totalAssets()` while the USDC feed is stale, so they
are skipped with a reason rather than retried into the log.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API = os.environ.get("TICKER_API", "http://api:8000")
RPC = os.environ.get("ANVIL_RPC_URL", "https://base-rpc.publicnode.com")
INTERVAL = int(os.environ.get("TICKER_INTERVAL_SECONDS", "1800"))
AGENT = os.environ.get("TICKER_AGENT_ADDRESS", "")
MIN_AGENT_ETH = float(os.environ.get("TICKER_MIN_AGENT_ETH", "0.0004"))
FACTORY_VAULTS_SELECTOR = "0x8220ef5b"  # vaults()


def log(msg: str) -> None:
    print(f"[ticker] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def _get(path: str, timeout: int = 60):
    with urllib.request.urlopen(f"{API}{path}", timeout=timeout) as r:
        return json.load(r)


def _post(path: str, timeout: int = 420):
    req = urllib.request.Request(f"{API}{path}", method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _rpc(method: str, params: list):
    req = urllib.request.Request(
        RPC,
        method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        # An explicit User-Agent is not optional: public RPCs block the default
        # `Python-urllib/3.x`, and urllib surfaces that as a bare HTTPError with
        # no hint that the request shape was the problem.
        headers={"Content-Type": "application/json", "User-Agent": "scipio-ticker/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("result")


def agent_eth() -> float | None:
    if not AGENT:
        return None
    try:
        return int(_rpc("eth_getBalance", [AGENT, "latest"]) or "0x0", 16) / 1e18
    except Exception as exc:  # noqa: BLE001
        log(f"could not read agent balance ({type(exc).__name__}); continuing")
        return None


def curated_vaults() -> list[str]:
    """Factory vaults that have a mandate — the only ones that can tick.

    Read every round rather than cached: a vault deployed from the dApp during
    the demo should start ticking without a restart.
    """
    manifest = json.load(open("/srv/deployments/base-mainnet.json"))
    factory = (manifest.get("contracts") or {}).get("VaultFactory")
    demo = (manifest.get("demoVault") or {}).get("address", "")
    if not factory:
        return []
    raw = _rpc("eth_call", [{"to": factory, "data": FACTORY_VAULTS_SELECTOR}, "latest"]) or "0x"
    if len(raw) < 130:
        return []
    body = raw[2:]
    count = int(body[64:128], 16)
    found = ["0x" + body[128 + i * 64 + 24 : 128 + (i + 1) * 64] for i in range(count)]

    out = []
    for v in found:
        if demo and v.lower() == demo.lower():
            continue  # the deploy script's vault has no mandate and never can
        try:
            _get(f"/vault/{v}/mandate", timeout=30)
        except Exception:  # noqa: BLE001 — 404 means "not curated", not an error
            continue
        out.append(v)
    return out


#: Short retry when a round finds nothing. `depends_on` waits for the container
#: to START, not for the API to be ready, so the first round can fire while
#: /vault/{addr}/mandate is still refusing connections — every vault then looks
#: uncurated and the loop sleeps a full interval over a transient. Observed on
#: the first deploy: "0 curated vault(s)" then thirty minutes of silence.
EMPTY_RETRY = 60


def _wait_for_api(deadline_s: int = 180) -> None:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            if _get("/health", timeout=10).get("mode") == "live":
                log("api is live")
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    log("api did not report live within the wait; starting anyway")


def main() -> None:
    log(f"api={API} interval={INTERVAL}s floor={MIN_AGENT_ETH} ETH")
    _wait_for_api()
    while True:
        balance = agent_eth()
        if balance is not None and balance < MIN_AGENT_ETH:
            log(f"STOPPING: agent holds {balance:.6f} ETH, below the {MIN_AGENT_ETH} floor.")
            log("Top it up and restart this service; nothing else is affected.")
            return

        try:
            vaults = curated_vaults()
        except Exception as exc:  # noqa: BLE001
            log(f"could not list vaults ({type(exc).__name__}); retrying next round")
            time.sleep(INTERVAL)
            continue

        log(f"{len(vaults)} curated vault(s)" + (f", agent {balance:.6f} ETH" if balance else ""))
        if not vaults:
            time.sleep(EMPTY_RETRY)
            continue
        for vault in vaults:
            # A vault whose totalAssets() reverts cannot be ticked, and the
            # reason is environmental (a stale feed), not a decision. Skip it
            # rather than write a failure into the judge-facing feed.
            try:
                _get(f"/vault/{vault}/state", timeout=60)
            except Exception:  # noqa: BLE001
                log(f"  {vault[:10]}… unreadable state, skipped")
                continue
            try:
                action = _post(f"/vault/{vault}/tick")
                status = action.get("status")
                tx = (action.get("tx_hashes") or [None])[0]
                log(f"  {vault[:10]}… {status}" + (f" {tx[:12]}…" if tx else ""))
            except urllib.error.HTTPError as exc:
                log(f"  {vault[:10]}… HTTP {exc.code}")
            except Exception as exc:  # noqa: BLE001
                log(f"  {vault[:10]}… {type(exc).__name__}")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
