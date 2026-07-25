"""`VaultClient` over web3.py, against Lane A's published ABIs.

The agent signs here. `plans/initiate_plan.md` §2 locks it: *"agent holds a key
and executes directly"*, with no human override. This module is where that stops
being a design statement and becomes a private key in memory.

## Why a plan is one `executeBatch`, not N calls to `execute`

Lane A exposes both. Sending each step separately means a plan can be *half*
applied — approval granted, swap reverted — leaving the vault in a state no
decision authored. `executeBatch` makes the whole plan atomic: it lands complete
or not at all, and the vault is only ever in a state the agent actually chose.
It also produces one transaction hash for the tick, which is what the decision
feed wants to show.

The `VaultClient` port says `execute` returns hashes "in order" and warns that a
partially-applied plan is a real outcome. With the batch path that outcome cannot
occur, which is strictly better than reporting it accurately.

## Share price

Computed from `totalAssets` and `totalSupply` with both decimals, rather than
read from `convertToAssets`, so the number matches the golden fixture's
definition exactly: assets per whole share in 1e18 fixed point. Two lanes
disagreeing about what "share price" scales to is the kind of thing that only
surfaces when a depositor sees the wrong number.

⚠️ The frozen interface disagrees with *itself* here, and this follows the
fixture. `vault-state.schema.json` describes the field as `convertToAssets(1e18)`
— 6-decimal for a USDC vault — while `fixtures/vault-state.json` carries
`1002506265664160401` for 50,000 USDC over 49,875 shares, which is the
dimensionless ratio × 1e18. The two differ by exactly 10¹². Request #50 asks
Lane F to rule; until it does, the fixture wins, because every lane's tests
validate against the fixture and nothing validates against the prose.

## Why `state()` reads in two waves

`/state` used to take 4.70s against a fork answering in 0.22s — about twenty
sequential round trips, and past the dApp's 4s read timeout, so the UI fell back
to reading the contract directly and showed "the agent API is unreachable" while
the agent was fine (#46). None of those reads depended on each other except
through `holdings()`, so they are now two `gather` waves: everything the vault
can answer about itself, then the per-token metadata that needs the holdings list
first. Token symbols and decimals are immutable, so they are also cached — the
second tick pays for wave 1 only.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from curator_schema import Holding, Mandate, VaultState
from eth_account import Account
from web3 import AsyncHTTPProvider
from web3.logs import DISCARD

from ..config import Settings
from .abi import ERC20_ABI, load_abi
from .receipts import underlying_symbol
from .rpc import make_async_web3

__all__ = ["Web3VaultClient"]

log = logging.getLogger(__name__)


def _selector(components) -> str:
    """The 4-byte selector for `createVault` taking this `CreateParams` shape."""
    from eth_utils import keccak

    types = ",".join(kind for _, kind in components)
    return keccak(text=f"createVault(({types}))")[:4].hex()


_SHARE_PRICE_SCALE = 10**18
#: Enough for an anvil fork; the real Base demo run is far below this.
_GAS_LIMIT = 3_000_000


def to_hex_string(value: bytes | str | None) -> str | None:
    """Normalize a chain value to `0x`-prefixed lowercase hex.

    Needed because `bytes.hex()` returns hex **without** the prefix, while
    `HexBytes.hex()` has included it in some versions and not others. The frozen
    schema requires `^0x[a-fA-F0-9]{64}$`, so an unprefixed digest fails
    validation at the API boundary — which is exactly how this was found, by
    reading a real deployed vault rather than a stub.
    """
    if value is None:
        return None
    raw = value.hex() if isinstance(value, bytes | bytearray) else str(value)
    return "0x" + raw.removeprefix("0x").lower()


class Web3VaultClient:
    """Reads vault state and submits plans, signing with the agent key."""

    name = "web3"

    def __init__(self, settings: Settings) -> None:
        if not settings.agent_private_key:
            raise ValueError(
                "AGENT_PRIVATE_KEY is required in live mode — the agent signs its own "
                "transactions, which is the trust model, not an implementation detail"
            )
        self._settings = settings
        self._w3 = make_async_web3(AsyncHTTPProvider(settings.rpc_url))
        self._account = Account.from_key(settings.agent_private_key)
        self._vault_abi = load_abi("CuratedVault")
        self._factory_abi = load_abi("VaultFactory")
        #: ERC-20 symbol and decimals never change for an address, so they are
        #: worth exactly one round trip per token for the life of the process.
        #: **Successful lookups only** — caching a failure would pin a token to
        #: its truncated-address placeholder until the next restart, turning one
        #: dropped RPC call into a permanently mislabelled holding.
        self._symbols: dict[str, str] = {}
        self._decimals: dict[str, int] = {}
        #: Resolved on the first deploy, because it costs an `eth_getCode` and
        #: the deployed factory does not change under a running process.
        self._create_params_cache: tuple[str, ...] | None = None
        log.info("agent signing as %s against %s", self._account.address, settings.rpc_url)

    @property
    def address(self) -> str:
        return self._account.address

    def _vault(self, vault: str):
        return self._w3.eth.contract(
            address=self._w3.to_checksum_address(vault), abi=self._vault_abi
        )

    # ── reads ─────────────────────────────────────────────────────────────

    def _placeholder(self, token: str) -> str:
        """What an unreadable token is called in the feed.

        ASCII on purpose. This string reaches the model's prompt through
        `_render_holdings`, and Lane C established that a Windows console turns a
        UTF-8 ellipsis into a mojibake box. A holding whose `symbol()` call
        failed is exactly the case no fixture covers, so the ASCII guard in
        `test_prompt_rendering.py` could never have caught it.
        """
        return f"{token[:6]}...{token[-4:]}"

    async def _symbol(self, token: str) -> str:
        """Best-effort ERC-20 symbol, cached.

        `holdings()` returns addresses; the feed shows names. A token that does
        not implement `symbol()` (or a non-standard one returning bytes32) must
        degrade to something renderable rather than failing the whole read.
        """
        key = token.lower()
        if (cached := self._symbols.get(key)) is not None:
            return cached
        try:
            erc20 = self._w3.eth.contract(
                address=self._w3.to_checksum_address(token), abi=ERC20_ABI
            )
            symbol = str(await erc20.functions.symbol().call())
        except Exception:  # noqa: BLE001
            return self._placeholder(token)
        self._symbols[key] = symbol
        return symbol

    async def _resolve_symbols(self, tokens: Sequence[str]) -> dict[str, str]:
        """Every token's symbol, concurrently and once each.

        Deduplicated before dispatch: a vault holding both a token and its
        receipt can list the same address twice, and paying twice for an
        immutable answer is the N+1 in miniature.
        """
        wanted = list(dict.fromkeys(token.lower() for token in tokens))
        resolved = await asyncio.gather(*(self._symbol(token) for token in wanted))
        return dict(zip(wanted, resolved, strict=True))

    async def state(self, vault: str) -> VaultState:
        fns = self._vault(vault).functions

        # Wave 1 — everything the vault can answer about itself. Independent of
        # each other, so one wall-clock round trip rather than eight (#46).
        (
            asset,
            total_assets,
            total_supply,
            share_decimals,
            raw_holdings,
            block_number,
            agent,
            mandate_hash,
        ) = await asyncio.gather(
            fns.asset().call(),
            fns.totalAssets().call(),
            fns.totalSupply().call(),
            fns.decimals().call(),
            fns.holdings().call(),
            self._w3.eth.block_number,
            self._maybe(fns.agent()),
            self._maybe(fns.mandateHash()),
        )

        # Wave 2 — the token metadata, which needed the holdings list to exist.
        # `holdings()` already carries each token's decimals, so the base asset's
        # usually costs nothing at all; the ERC-20 call is the fallback for a
        # vault holding none of its own asset.
        by_token = {row[0].lower(): int(row[1]) for row in raw_holdings}
        symbols, asset_decimals = await asyncio.gather(
            self._resolve_symbols([row[0] for row in raw_holdings]),
            self._asset_decimals(asset, by_token),
        )

        holdings: list[Holding] = [
            Holding(
                token=token,
                symbol=symbols[token.lower()],
                balance=str(balance),
                decimals=int(decimals),
                value_in_asset=str(value_in_asset),
            )
            for token, decimals, balance, value_in_asset in raw_holdings
        ]

        # Second pass, because resolving a receipt token's underlying prefers a
        # symbol the vault is already reporting — which needs every holding
        # named first. See `agent/chain/receipts.py` for why this matters:
        # unfolded, a supplied balance reads as an asset the mandate never
        # permitted and every constraint layer fights it. Local, no round trips.
        holdings = [
            h.model_copy(update={"represents": represented, "committed_to_venue": "aave"})
            if (represented := underlying_symbol(h.token, symbols)) is not None
            else h
            for h in holdings
        ]

        return VaultState(
            address=self._w3.to_checksum_address(vault),
            asset=asset,
            total_assets=str(total_assets),
            total_supply=str(total_supply),
            asset_decimals=asset_decimals,
            share_price=_share_price(total_assets, total_supply, asset_decimals, share_decimals),
            holdings=holdings,
            agent=agent,
            mandate_hash=to_hex_string(mandate_hash),
            block_number=block_number,
        )

    async def _asset_decimals(self, asset: str, from_holdings: dict[str, int]) -> int:
        """The base asset's decimals, preferring the answer already in hand.

        `holdings()` reports decimals per token and Lane A guarantees index 0 is
        the base asset (#13), so the common path costs no round trip. The ERC-20
        call remains for the case that guarantee does not cover — a vault holding
        none of its own asset — and 6 is the last resort rather than a default,
        because a wrong scaling here misreports the vault by 10¹².
        """
        key = asset.lower()
        if (known := from_holdings.get(key)) is not None:
            return known
        if (cached := self._decimals.get(key)) is not None:
            return cached
        try:
            erc20 = self._w3.eth.contract(
                address=self._w3.to_checksum_address(asset), abi=ERC20_ABI
            )
            decimals = int(await erc20.functions.decimals().call())
        except Exception:  # noqa: BLE001
            log.warning("could not read decimals() for %s; assuming 6", asset)
            return 6
        self._decimals[key] = decimals
        return decimals

    async def _maybe(self, call) -> Any | None:
        """Optional view — absent from an older deployment is not an error."""
        try:
            return await call.call()
        except Exception:  # noqa: BLE001
            return None

    # ── writes ────────────────────────────────────────────────────────────

    async def _send(self, function) -> str:
        """Sign, submit and wait. Raises if the transaction reverts."""
        nonce = await self._w3.eth.get_transaction_count(self._account.address)
        tx = await function.build_transaction(
            {
                "from": self._account.address,
                "nonce": nonce,
                "gas": _GAS_LIMIT,
                "chainId": self._settings.chain_id,
            }
        )
        signed = self._account.sign_transaction(tx)
        tx_hash = await self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = await self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        if receipt["status"] != 1:
            raise RuntimeError(f"transaction {tx_hash.hex()} reverted")
        return "0x" + tx_hash.hex().removeprefix("0x")

    async def execute(self, vault: str, plan) -> list[str]:
        """Submit the whole plan as one atomic batch."""
        calls = [
            (
                self._w3.to_checksum_address(step.target),
                int(step.value),
                bytes.fromhex(step.calldata.removeprefix("0x")),
            )
            for step in plan.steps
        ]
        log.info("executing %d step(s) on %s", len(calls), vault)
        return [await self._send(self._vault(vault).functions.executeBatch(calls))]

    async def deploy(
        self, mandate: Mandate, mandate_hash: str, deployer: str | None = None
    ) -> tuple[str, str]:
        """Clone a vault via Lane A's factory, bound to this mandate's hash.

        `deployer` is Lane A's §A1 attribution field and is **read off the ABI
        rather than assumed**, because this lane and `contracts/` ship
        independently: the field appeared mid-wave and a hardcoded 7-tuple would
        have broken every deploy until Lane A landed, while a hardcoded 6-tuple
        breaks every deploy after. Building the arguments from the ABI's own
        component names means neither ordering of those two events matters.

        The agent still submits the transaction, so this records *who asked*.
        It is not a signature and Lane A's `SECURITY.md` says so.
        """
        if not self._settings.factory_address:
            raise ValueError(
                "VAULT_FACTORY_ADDRESS is not set; it is written to "
                "deployments/base-fork.json by Lane A's deploy script"
            )

        factory = self._w3.eth.contract(
            address=self._w3.to_checksum_address(self._settings.factory_address),
            abi=self._factory_abi,
        )
        asset = await self._resolve_asset(mandate)
        by_name = {
            "asset": asset,
            "name": f"Curated {mandate.name}"[:64],
            "symbol": "cv" + mandate.base_asset[:6],
            "agent": self._account.address,
            "guardian": self._account.address,
            "mandateHash": bytes.fromhex(mandate_hash.removeprefix("0x")),
            # Falls back to the submitter, which is the truth when no wallet was
            # connected: the agent really is who asked for it.
            "deployer": self._w3.to_checksum_address(deployer)
            if deployer
            else self._account.address,
        }
        params = tuple(by_name[c] for c in await self._create_params_fields())

        tx_hash = await self._send(factory.functions.createVault(params))
        receipt = await self._w3.eth.get_transaction_receipt(tx_hash)
        # DISCARD, not the default WARN: creating a vault also emits the clone's
        # own initialization events, which cannot decode against the factory ABI
        # and are not supposed to. The default prints a MismatchedABI warning per
        # undecodable log — four scary paragraphs during a genesis demo, for
        # nothing.
        events = factory.events.VaultCreated().process_receipt(receipt, errors=DISCARD)
        if not events:
            raise RuntimeError(f"createVault in {tx_hash} emitted no VaultCreated event")
        return events[0]["args"]["vault"], tx_hash

    #: The shape `CreateParams` had before Lane A's §A1 attribution field, with
    #: the Solidity types needed to compute its selector. Kept because
    #: `contracts/out/` and the deployed factory are published by the same lane
    #: but at different moments — see `_create_params_fields`.
    _LEGACY_CREATE_PARAMS = (
        ("asset", "address"),
        ("name", "string"),
        ("symbol", "string"),
        ("agent", "address"),
        ("guardian", "address"),
        ("mandateHash", "bytes32"),
    )

    def _abi_create_params(self) -> tuple[tuple[str, str], ...] | None:
        """`CreateParams` as the published ABI declares it, name and type."""
        for entry in self._factory_abi:
            if entry.get("name") != "createVault" or entry.get("type") != "function":
                continue
            inputs = entry.get("inputs") or []
            if inputs and (components := inputs[0].get("components")):
                return tuple((c["name"], c["type"]) for c in components)
        return None

    async def _create_params_fields(self) -> tuple[str, ...]:
        """The argument order the **deployed** factory actually accepts.

        Read from the ABI so a field added in `contracts/` needs no change here,
        then **checked against the deployed bytecode**, which is the part that
        matters: `contracts/out/` is committed on purpose so other lanes get the
        ABI early, so there is a real window in which the artifact has a field
        the running contract does not.

        That window cost a reverted `createVault` once already. The ABI declared
        the seven-field `CreateParams` from §A1 while the fork was still running
        the six-field one, so the call encoded cleanly, went out with a selector
        nothing on-chain implements, and came back as a bare `reverted` — which
        reads as a bad mandate rather than a stale deployment.

        A component this code has no value for raises `KeyError` naming it,
        which beats silently passing the wrong argument in that slot.
        """
        declared = self._abi_create_params()
        if declared is None:
            log.warning("no CreateParams in the factory ABI; assuming the pre-A1 shape")
            return tuple(name for name, _ in self._LEGACY_CREATE_PARAMS)
        if self._create_params_cache is not None:
            return self._create_params_cache

        fields = tuple(name for name, _ in declared)
        try:
            code = (await self._w3.eth.get_code(
                self._w3.to_checksum_address(self._settings.factory_address)
            )).hex()
        except Exception as exc:  # noqa: BLE001 - trust the ABI if we cannot look
            log.warning("could not read the factory's bytecode (%s); trusting the ABI", exc)
            return fields

        if _selector(declared) not in code:
            which = (
                "it is still the pre-A1 six-field one"
                if _selector(self._LEGACY_CREATE_PARAMS) in code
                else "no known shape matches"
            )
            raise RuntimeError(
                f"the factory at {self._settings.factory_address} does not implement the "
                f"createVault that contracts/out/VaultFactory.json declares ({which}). "
                f"The ABI artifact is committed ahead of the deployment, so this is a stale "
                f"factory rather than a bad mandate — Lane A needs to redeploy and update "
                f"deployments/base-fork.json. Nothing was deployed."
            )

        self._create_params_cache = fields
        return fields

    async def _resolve_asset(self, mandate: Mandate) -> str:
        """Map the mandate's base-asset symbol to an address.

        Read from Lane A's `deployments/base-fork.json`, which is the shared
        published record of external addresses — hardcoding USDC here would put a
        chain constant in the harness and guarantee it drifts.
        """
        import json

        from ..config import REPO_ROOT

        path = REPO_ROOT / "deployments" / "base-fork.json"
        external = json.loads(path.read_text(encoding="utf-8")).get("external", {})
        address = external.get(mandate.base_asset)
        if not address:
            raise ValueError(
                f"no address for base asset {mandate.base_asset} in {path.name}; "
                "add it under `external` or deploy against a known asset"
            )
        return self._w3.to_checksum_address(address)


def _share_price(
    total_assets: int, total_supply: int, asset_decimals: int, share_decimals: int
) -> str | None:
    """Assets per whole share, in 1e18 fixed point."""
    if total_supply == 0:
        return None
    scaled = total_assets * (10**share_decimals) * _SHARE_PRICE_SCALE
    return str(scaled // (total_supply * (10**asset_decimals)))
