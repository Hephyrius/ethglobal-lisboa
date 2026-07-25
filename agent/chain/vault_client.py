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
"""

from __future__ import annotations

import logging
from typing import Any

from curator_schema import Holding, Mandate, VaultState
from eth_account import Account
from web3 import AsyncHTTPProvider, AsyncWeb3
from web3.logs import DISCARD

from ..config import Settings
from .abi import ERC20_ABI, load_abi

__all__ = ["Web3VaultClient"]

log = logging.getLogger(__name__)

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
        self._w3 = AsyncWeb3(AsyncHTTPProvider(settings.rpc_url))
        self._account = Account.from_key(settings.agent_private_key)
        self._vault_abi = load_abi("CuratedVault")
        self._factory_abi = load_abi("VaultFactory")
        log.info("agent signing as %s against %s", self._account.address, settings.rpc_url)

    @property
    def address(self) -> str:
        return self._account.address

    def _vault(self, vault: str):
        return self._w3.eth.contract(
            address=self._w3.to_checksum_address(vault), abi=self._vault_abi
        )

    # ── reads ─────────────────────────────────────────────────────────────

    async def _symbol(self, token: str) -> str:
        """Best-effort ERC-20 symbol.

        `holdings()` returns addresses; the feed shows names. A token that does
        not implement `symbol()` (or a non-standard one returning bytes32) must
        degrade to something renderable rather than failing the whole read.
        """
        try:
            erc20 = self._w3.eth.contract(
                address=self._w3.to_checksum_address(token), abi=ERC20_ABI
            )
            return await erc20.functions.symbol().call()
        except Exception:  # noqa: BLE001
            return f"{token[:6]}…{token[-4:]}"

    async def state(self, vault: str) -> VaultState:
        contract = self._vault(vault)
        fns = contract.functions

        asset = await fns.asset().call()
        total_assets = await fns.totalAssets().call()
        total_supply = await fns.totalSupply().call()
        share_decimals = await fns.decimals().call()
        raw_holdings = await fns.holdings().call()
        block_number = await self._w3.eth.block_number

        agent = await self._maybe(fns.agent())
        mandate_hash = await self._maybe(fns.mandateHash())
        asset_decimals = await self._token_decimals(asset)

        holdings: list[Holding] = []
        for token, decimals, balance, value_in_asset in raw_holdings:
            holdings.append(
                Holding(
                    token=token,
                    symbol=await self._symbol(token),
                    balance=str(balance),
                    decimals=int(decimals),
                    value_in_asset=str(value_in_asset),
                )
            )

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

    async def _token_decimals(self, token: str) -> int:
        try:
            erc20 = self._w3.eth.contract(
                address=self._w3.to_checksum_address(token), abi=ERC20_ABI
            )
            return int(await erc20.functions.decimals().call())
        except Exception:  # noqa: BLE001
            return 6

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

    async def deploy(self, mandate: Mandate, mandate_hash: str) -> tuple[str, str]:
        """Clone a vault via Lane A's factory, bound to this mandate's hash."""
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
        params = (
            asset,
            f"Curated {mandate.name}"[:64],
            "cv" + mandate.base_asset[:6],
            self._account.address,
            self._account.address,
            bytes.fromhex(mandate_hash.removeprefix("0x")),
        )

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
