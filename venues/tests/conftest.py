"""Shared test fixtures for the venue adapters.

Two classes of test live here and they are kept strictly apart:

* **offline** — replay recorded API responses from `fixtures/`. No network, no
  credentials, deterministic. These are the ones that must always be green.
* **live** (`@pytest.mark.live`) — hit the real gateway. Skipped automatically
  when the credential is absent so a fresh clone still passes, and run
  explicitly with `-m live`. The demo path uses live data; these prove it.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from venues.config import VenueConfig

FIXTURES = Path(__file__).parent / "fixtures"

#: Frozen clock so time-dependent plan fields are assertable.
FIXED_NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def pytest_configure(config: pytest.Config) -> None:
    # Registered here rather than in the root pyproject so this lane does not
    # need to edit a shared file to add its own marker.
    config.addinivalue_line("markers", "live: hits a real network endpoint")


@pytest.fixture(scope="session")
def config() -> VenueConfig:
    return VenueConfig.from_env()


@pytest.fixture(scope="session")
def requires_uniswap_key(config: VenueConfig) -> str:
    if not config.uniswap_api_key:
        pytest.skip("UNISWAP_API_KEY not set — skipping live Uniswap test")
    return config.uniswap_api_key


@pytest.fixture
def quote_response() -> dict[str, Any]:
    """Recorded `POST /quote` — 1 USDC → WETH on Base, captured 2026-07-25."""
    return load_fixture("uniswap-quote-usdc-weth.json")


@pytest.fixture
def swap_response() -> dict[str, Any]:
    """Recorded `POST /swap` for the quote above."""
    return load_fixture("uniswap-swap-usdc-weth.json")


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
async def anvil_rpc(config: VenueConfig):
    """An RPC that supports `eth_call` state overrides.

    The program builder is a *pure* contract, so this needs no Base fork and no
    archive node — a bare `anvil` is enough, which keeps this lane's live tests
    running even while `BASE_RPC_URL` is unset. Skips rather than fails when
    nothing is listening, so the suite stays green on a fresh clone.
    """

    from venues.rpc import RpcClient

    url = os.environ.get("VENUES_TEST_RPC_URL", "http://localhost:8547")
    client = RpcClient(url)
    try:
        await client.request("eth_blockNumber", [])
    except Exception as exc:  # noqa: BLE001 — any failure means "no node here"
        await client.aclose()
        pytest.skip(
            f"no JSON-RPC at {url} ({type(exc).__name__}). Start one with:\n"
            f"  wsl -d Ubuntu-24.04 -- anvil --host 0.0.0.0 --port 8547\n"
            f"or set VENUES_TEST_RPC_URL."
        )
    try:
        yield client
    finally:
        await client.aclose()
