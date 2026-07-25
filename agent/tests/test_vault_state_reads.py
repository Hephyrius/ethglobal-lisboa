"""`/state` must not go back to being an N+1 (request #46).

Wave 0 measured `GET /vault/{addr}/state` at **4.70s** against a fork answering
individual calls in 0.22s — roughly twenty sequential round trips. The dApp's
read timeout is 4000ms, so every state read missed it, the UI fell back to
reading the ERC-4626 contract directly, and the banner said *"the agent API is
unreachable"* while the agent was perfectly healthy. During a demo that reads as
a dead agent.

Nothing about the fix is clever — the reads were always independent, they were
just awaited one at a time. What is worth pinning is that they **stay**
independent, because the regression is invisible: adding one more `await` inside
the holdings loop costs 0.22s per token and breaks no test that only checks the
returned `VaultState`.

So these tests assert against a counting provider rather than a live chain:

- **how many** round trips a read costs, so an N+1 fails loudly;
- **peak concurrency**, which is the part a call-count alone cannot prove — 15
  calls issued one at a time and 15 issued together are indistinguishable by
  count and differ by 3.3s;
- that the **second** read is cheaper, since token symbols and decimals are
  immutable and a demo polls this route.

The provider answers from canned ABI-encoded values, so this needs no anvil and
runs in milliseconds.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from eth_abi.abi import encode
from eth_utils.abi import function_abi_to_4byte_selector
from web3 import AsyncHTTPProvider

from agent.chain.abi import ERC20_ABI, load_abi
from agent.chain.rpc import make_async_web3
from agent.chain.vault_client import Web3VaultClient
from agent.config import Settings

VAULT = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
AGENT = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
DIGEST = bytes.fromhex("d0" * 32)

#: The measured per-round-trip cost on the fork, scaled down so the suite stays
#: fast. Ratios are what matter, not the absolute number.
LATENCY = 0.02


def _type_of(entry: dict) -> str:
    """ABI output entry -> canonical type string, tuples included.

    web3 7.16 exposes no public helper for this — `get_abi_output_types` is gone
    from both `web3.utils.abi` and `web3._utils.abi`.
    """
    if entry["type"].startswith("tuple"):
        inner = ",".join(_type_of(c) for c in entry["components"])
        return f"({inner}){entry['type'].removeprefix('tuple')}"
    return entry["type"]


def _outputs(abi: list[dict], name: str) -> list[str]:
    fn = next(e for e in abi if e.get("name") == name and e.get("type") == "function")
    return [_type_of(o) for o in fn["outputs"]]


def _selector(abi: list[dict], name: str) -> str:
    fn = next(e for e in abi if e.get("name") == name and e.get("type") == "function")
    return "0x" + function_abi_to_4byte_selector(fn).hex()


VAULT_ABI = load_abi("CuratedVault")

#: selector -> (output types, value). Anything not listed reverts, which is how
#: an unexpected extra read announces itself instead of silently passing.
ANSWERS = {
    _selector(VAULT_ABI, "asset"): (_outputs(VAULT_ABI, "asset"), USDC),
    _selector(VAULT_ABI, "totalAssets"): (_outputs(VAULT_ABI, "totalAssets"), 2_500_000000),
    _selector(VAULT_ABI, "totalSupply"): (
        _outputs(VAULT_ABI, "totalSupply"),
        2_500 * 10**18,
    ),
    _selector(VAULT_ABI, "decimals"): (_outputs(VAULT_ABI, "decimals"), 18),
    _selector(VAULT_ABI, "agent"): (_outputs(VAULT_ABI, "agent"), AGENT),
    _selector(VAULT_ABI, "mandateHash"): (_outputs(VAULT_ABI, "mandateHash"), DIGEST),
    _selector(VAULT_ABI, "holdings"): (
        _outputs(VAULT_ABI, "holdings"),
        [
            (USDC, 6, 1_750_000000, 1_750_000000),
            (WETH, 18, 250 * 10**15, 750_000000),
        ],
    ),
}

#: `symbol()` collides across every ERC-20, so it is answered by the `to` address
#: rather than the selector — which is the whole point: one call per token.
SYMBOLS = {USDC.lower(): "USDC", WETH.lower(): "WETH"}
SYMBOL_SELECTOR = _selector(ERC20_ABI, "symbol")


class CountingProvider(AsyncHTTPProvider):
    """Answers canned values, counts round trips, and records peak concurrency."""

    def __init__(self, latency: float = LATENCY) -> None:
        super().__init__("http://127.0.0.1:1")  # never contacted
        self.latency = latency
        self.calls: list[str] = []
        self._in_flight = 0
        self.peak_in_flight = 0

    @property
    def round_trips(self) -> int:
        return len(self.calls)

    def count(self, label: str) -> int:
        return sum(1 for c in self.calls if c == label)

    async def make_request(self, method: str, params):  # type: ignore[override]
        self.calls.append(self._label(method, params))
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            await asyncio.sleep(self.latency)
            return {"jsonrpc": "2.0", "id": 1, "result": self._result(method, params)}
        finally:
            self._in_flight -= 1

    @staticmethod
    def _call_data(params) -> tuple[str, str]:
        tx = params[0]
        data = tx.get("data") or tx.get("input") or ""
        data = data if isinstance(data, str) else "0x" + bytes(data).hex()
        to = tx.get("to") or ""
        return (str(to).lower(), data.lower())

    def _label(self, method: str, params) -> str:
        if method != "eth_call":
            return method
        to, data = self._call_data(params)
        if data[:10] == SYMBOL_SELECTOR:
            return f"symbol({to[:8]})"
        return data[:10]

    def _result(self, method: str, params):
        if method == "eth_blockNumber":
            return hex(490_777)
        if method == "eth_chainId":
            return hex(8453)
        if method != "eth_call":
            raise AssertionError(f"unexpected RPC method {method}")

        to, data = self._call_data(params)
        if data[:10] == SYMBOL_SELECTOR:
            return "0x" + encode(["string"], [SYMBOLS[to]]).hex()
        types, value = ANSWERS[data[:10]]
        return "0x" + encode(types, [value]).hex()


def _client(latency: float = LATENCY) -> tuple[Web3VaultClient, CountingProvider]:
    vault_client = Web3VaultClient(
        Settings(rpc_url="http://127.0.0.1:1", agent_private_key="0x" + "11" * 32)
    )
    provider = CountingProvider(latency)
    # Built the same way production builds it — a round-trip count taken against
    # a differently-assembled web3 would be measuring the wrong object.
    vault_client._w3 = make_async_web3(provider)
    return vault_client, provider


@pytest.fixture
def client() -> tuple[Web3VaultClient, CountingProvider]:
    return _client()


# ── the read is still correct ─────────────────────────────────────────────


async def test_the_state_read_is_unchanged_by_the_batching(client):
    """Everything below is worthless if the faster read returns different data."""
    vault_client, _ = client
    state = await vault_client.state(VAULT)

    assert state.address == VAULT
    assert state.asset.lower() == USDC.lower()
    assert state.total_assets == "2500000000"
    assert state.share_price == str(10**18), "2,500 USDC over 2,500 shares is exactly 1.0"
    assert state.asset_decimals == 6
    assert state.agent == AGENT
    assert state.mandate_hash == "0x" + "d0" * 32
    assert state.block_number == 490_777
    assert [(h.symbol, h.balance) for h in state.holdings] == [
        ("USDC", "1750000000"),
        ("WETH", "250000000000000000"),
    ]


# ── the shape of the read ─────────────────────────────────────────────────


async def test_one_state_read_costs_far_fewer_round_trips_than_it_did(client):
    """28 was the measured cost of the first read; 11 is what it costs now.

    Eight vault reads, one `symbol()` per token, and a single `eth_chainId` —
    with the base asset's decimals taken from `holdings()` rather than asked for
    separately. The bound is what fails a regression.
    """
    vault_client, provider = client
    await vault_client.state(VAULT)

    assert provider.round_trips <= 11, f"N+1 is back: {provider.calls}"


async def test_the_reads_actually_overlap(client):
    """**The assertion a call count cannot make.** Fifteen calls issued one at a
    time and fifteen issued together are identical by count and 3.3s apart on the
    fork. Peak concurrency is the thing that was actually broken."""
    vault_client, provider = client
    await vault_client.state(VAULT)

    assert provider.peak_in_flight >= 6, (
        f"reads are still sequential (peak in flight: {provider.peak_in_flight})"
    )


async def test_the_read_costs_waves_of_latency_rather_than_calls():
    """Wall clock scales with **waves**, not round trips — the whole of #46.

    Measured differentially rather than absolutely, because a single read carries
    ~0.15s of one-off Python cost (ABI parsing, codec and contract construction)
    that dwarfs a fast local latency and has nothing to do with what broke. Two
    latencies, same work: the fixed cost cancels in the subtraction and what is
    left is purely what the network contributed.
    """
    fast, slow = 0.005, 0.05

    async def elapsed(latency: float) -> float:
        vault_client, _ = _client(latency)
        await vault_client.state(VAULT)  # warm the caches, then measure
        started = time.perf_counter()
        await vault_client.state(VAULT)
        return time.perf_counter() - started

    network = await elapsed(slow) - await elapsed(fast)
    per_wave = slow - fast

    # A warm read is 8 round trips in one wave. Sequential would be 8 waves;
    # three is loose enough for a loaded CI box and nowhere near eight.
    assert network < 3 * per_wave, (
        f"{network * 1000:.0f}ms of latency for one wave of reads — "
        f"sequential would be ~{8 * per_wave * 1000:.0f}ms"
    )


async def test_each_token_is_named_once_per_read(client):
    """A vault can list the same address twice — a token and its receipt — and
    paying twice for an immutable answer is the N+1 in miniature."""
    vault_client, provider = client
    await vault_client.state(VAULT)

    assert provider.count(f"symbol({USDC.lower()[:8]})") == 1
    assert provider.count(f"symbol({WETH.lower()[:8]})") == 1


# ── the cache ─────────────────────────────────────────────────────────────


async def test_the_second_read_is_cheaper_than_the_first(client):
    """Symbols and decimals are immutable, and the dApp polls this route."""
    vault_client, provider = client

    await vault_client.state(VAULT)
    first = provider.round_trips
    provider.calls.clear()
    await vault_client.state(VAULT)

    assert provider.round_trips < first
    assert not [c for c in provider.calls if c.startswith("symbol(")], (
        "an immutable symbol was fetched twice"
    )


async def test_balances_are_never_cached(client):
    """The cache is for metadata only. A cached `totalAssets` would show a stale
    vault — the failure this is trading against."""
    vault_client, provider = client

    await vault_client.state(VAULT)
    provider.calls.clear()
    await vault_client.state(VAULT)

    assert _selector(VAULT_ABI, "totalAssets") in provider.calls
    assert _selector(VAULT_ABI, "holdings") in provider.calls


async def test_an_unreadable_symbol_is_not_cached(client):
    """**The trap in caching.** A dropped RPC call would otherwise pin a token to
    its truncated-address placeholder for the life of the process, turning one
    transient failure into a permanently mislabelled holding."""
    vault_client, provider = client
    del SYMBOLS[WETH.lower()]
    try:
        first = await vault_client.state(VAULT)
        assert first.holdings[1].symbol.startswith("0x4200")
        SYMBOLS[WETH.lower()] = "WETH"
        second = await vault_client.state(VAULT)
    finally:
        SYMBOLS[WETH.lower()] = "WETH"

    assert second.holdings[1].symbol == "WETH", "a failed lookup was cached"


async def test_the_placeholder_symbol_is_ascii(client):
    """It reaches the model's prompt through `_render_holdings`, and Lane C
    established that a Windows console turns a UTF-8 ellipsis into a mojibake
    box. No fixture covers a token whose `symbol()` reverted, so the prompt's
    ASCII guard could never have caught this one."""
    vault_client, _ = client
    del SYMBOLS[WETH.lower()]
    try:
        state = await vault_client.state(VAULT)
    finally:
        SYMBOLS[WETH.lower()] = "WETH"

    placeholder = state.holdings[1].symbol
    assert not [c for c in placeholder if ord(c) > 127], placeholder


# ── the chain id nobody asked for ─────────────────────────────────────────


async def test_the_chain_id_is_fetched_once_for_the_whole_connection(client):
    """**Two thirds of the original 28 round trips.** web3's validation
    middleware does `await async_w3.eth.chain_id` in its per-request path, so
    every `eth_call` quietly paid for a second round trip — 18 requests nothing
    in this repo asked for."""
    vault_client, provider = client

    await vault_client.state(VAULT)
    await vault_client.state(VAULT)

    assert provider.count("eth_chainId") == 1, "the chain id is being refetched"


async def test_concurrent_first_reads_do_not_stampede(client):
    """The reason the cache needs a lock. Batching the vault reads means all
    eight miss an empty cache simultaneously; without coalescing the cache alone
    only got 28 down to 17."""
    vault_client, provider = client

    await asyncio.gather(vault_client.state(VAULT), vault_client.state(VAULT))

    assert provider.count("eth_chainId") == 1


async def test_a_failed_chain_id_is_never_cached():
    """A stuck chain id feeds the guard deciding whether a signed transaction is
    going to the right chain, so a node that was briefly unreachable must not
    pin the connection to a failure it has already recovered from."""
    from agent.chain.rpc import CachedChainId

    calls: list[str] = []
    replies = [
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}},
        {"jsonrpc": "2.0", "id": 1, "result": hex(8453)},
    ]

    async def make_request(method, params):
        calls.append(method)
        return replies.pop(0)

    middleware = await CachedChainId(None).async_wrap_make_request(make_request)

    assert "error" in await middleware("eth_chainId", [])
    assert (await middleware("eth_chainId", []))["result"] == hex(8453)
    assert (await middleware("eth_chainId", []))["result"] == hex(8453)
    assert calls == ["eth_chainId", "eth_chainId"], "the error was cached, or the success was not"
