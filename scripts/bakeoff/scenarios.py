"""The fixed situations every candidate model is asked to decide.

A bake-off is only as good as its scenarios, so these are chosen to separate models rather than to
flatter them. Each one has a *right shape of answer* that is derivable from the mandate and the
book, which is what makes scoring possible without a human in the loop.

Built from `packages/schema/fixtures/` and `packages/schema/presets/` rather than invented, so the
prompt a candidate sees is the prompt the real harness would build from real shapes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from curator_schema import Holding, Mandate, MarketSnapshot, VaultState

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "packages" / "schema"
FIXTURES = SCHEMA_DIR / "fixtures"
PRESETS = SCHEMA_DIR / "presets"

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
VAULT = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def preset(key: str) -> Mandate:
    return Mandate.model_validate(_load(PRESETS / f"{key}.json"))


def snapshot() -> MarketSnapshot:
    """The golden snapshot. Its facts are what `facts_used` is scored against."""
    return MarketSnapshot.model_validate(_load(FIXTURES / "market-snapshot.json"))


def _vault(usdc_units: int, weth_wei: int, *, committed: str | None = None) -> VaultState:
    """A vault holding exactly what the scenario says, valued at $1 and $1,858.

    `value_in_asset` is set explicitly rather than derived: these scenarios must be reproducible
    on a machine with no chain, and a model reading a book has to be shown the same numbers every
    run or the measurement moves under you.
    """
    weth_value = int(weth_wei * 1858 / 10**12)  # 18-decimal wei -> 6-decimal USDC
    holdings = [
        Holding(
            token=USDC, symbol="USDC", balance=str(usdc_units), decimals=6,
            value_in_asset=str(usdc_units),
        )
    ]
    if weth_wei:
        holdings.append(
            Holding(
                token=WETH, symbol="WETH", balance=str(weth_wei), decimals=18,
                value_in_asset=str(weth_value), committed_to_venue=committed,
            )
        )
    total = usdc_units + weth_value
    return VaultState(
        address=VAULT, asset=USDC, total_assets=str(total),
        total_supply=str(total * 10**12), holdings=holdings, asset_decimals=6,
        agent="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        block_number=49078117,
    )


@dataclass(frozen=True)
class Scenario:
    key: str
    #: What a competent curator should do. Scored structurally, never by reading the prose.
    expects: str
    why: str
    mandate: Mandate
    vault: VaultState
    #: Intent kinds that count as the right shape of answer. Empty means "hold is acceptable".
    wanted_intents: tuple[str, ...]
    #: `hold` is a first-class answer everywhere except where the book makes it indefensible.
    hold_is_defensible: bool


def all_scenarios() -> list[Scenario]:
    return [
        Scenario(
            key="idle-cash",
            expects="supply idle USDC to a lending market",
            why=(
                "The whole book is cash under a mandate whose only venue is Aave and whose "
                "objective says unlent USDC above the floor earns nothing. There is no asset to "
                "rotate into and nothing to rebalance, so lending is the only action available "
                "and holding means declining the mandate's stated purpose."
            ),
            mandate=preset("conservative-income"),
            vault=_vault(2_500_000_000, 0),
            wanted_intents=("supply",),
            hold_is_defensible=False,
        ),
        Scenario(
            key="balanced-ship",
            expects="ship into Aqua, or supply the idle leg",
            why=(
                "This is the exact situation the 3B failed three times (#51b): a book sitting ON "
                "its 50/50 target, where the mandate permits Aqua market-making on inventory the "
                "vault already holds. The trap is concluding that a balanced book means nothing "
                "to do — the 3B went further and proposed liquidating the whole WETH leg while "
                "asserting 50% does not match 50%."
            ),
            mandate=preset("balanced-two-asset"),
            vault=_vault(1_250_000_000, 672_000_000_000_000_000),
            wanted_intents=("ship", "supply"),
            hold_is_defensible=False,
        ),
        Scenario(
            key="drifted",
            expects="swap WETH back toward the target",
            why=(
                "80/20 against a 50/50 target and a 60% position cap: WETH is over the cap, so "
                "the correction direction is unambiguous. A model that swaps the wrong way "
                "increases the breach, which is a failure mode we have seen on-chain (#27)."
            ),
            mandate=preset("balanced-two-asset"),
            vault=_vault(500_000_000, 1_076_000_000_000_000_000),
            wanted_intents=("swap",),
            hold_is_defensible=False,
        ),
        Scenario(
            key="already-deployed",
            expects="hold",
            why=(
                "The control, and the one scenario where holding is the right answer: the cash "
                "floor is exactly met and the rest is already committed to a venue. A model that "
                "trades here is churning, which is the failure the six validation layers exist to "
                "prevent — so a harness that only rewarded action would be measuring the wrong "
                "thing."
            ),
            mandate=preset("balanced-two-asset"),
            vault=_vault(500_000_000, 1_076_000_000_000_000_000, committed="aqua"),
            wanted_intents=(),
            hold_is_defensible=True,
        ),
    ]


def scenario(key: str) -> Scenario:
    for s in all_scenarios():
        if s.key == key:
            return s
    raise KeyError(f"no scenario {key!r}; have {[s.key for s in all_scenarios()]}")


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)
