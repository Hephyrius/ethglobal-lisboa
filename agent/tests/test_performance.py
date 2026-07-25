"""P2 — the share-price series and the figures derived from it.

Most of these tests are about a single discipline: **the summary says None when
it does not know, and never 0.0**. A volatility of 0.0% and "we have three
points" render identically in a UI and mean opposite things, and the reader is
someone deciding whether to hand an autonomous agent money.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from curator_schema import AllocationSlice, Holding, PerformancePoint, VaultState

from agent.performance import PerformanceStore, point_from_state, summarize
from agent.performance.metrics import MIN_OBSERVATIONS_FOR_RISK
from agent.performance.window import window_points

VAULT = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"
_T0 = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _point(
    minutes: int, price: int, *, block: int | None = None, supply: int = 10**18
) -> PerformancePoint:
    return PerformancePoint(
        timestamp=_T0 + timedelta(minutes=minutes),
        block_number=block if block is not None else 49_000_000 + minutes,
        share_price=str(price),
        total_assets=str(price * 10_000),
        total_supply=str(supply),
    )


def _series(prices: list[int], *, step_minutes: int = 60) -> list[PerformancePoint]:
    return [_point(i * step_minutes, price) for i, price in enumerate(prices)]


# ── the None discipline ───────────────────────────────────────────────────


def test_an_empty_series_reports_nothing_rather_than_zero():
    summary = summarize(VAULT, [])
    assert summary.observations == 0
    assert summary.return_pct is None
    assert summary.max_drawdown_pct is None
    assert summary.volatility_pct is None


def test_one_point_is_a_position_not_a_performance():
    summary = summarize(VAULT, _series([1_000_000]))
    assert summary.observations == 1
    assert summary.share_price == "1000000"
    assert summary.return_pct is None, "a single price cannot produce a return"


def test_volatility_is_none_below_the_observation_floor():
    """Seven points is not a small volatility, it is an unknown one."""
    series = _series([1_000_000 + i * 100 for i in range(MIN_OBSERVATIONS_FOR_RISK - 1)])
    assert summarize(VAULT, series).volatility_pct is None


def test_annualization_refuses_a_span_shorter_than_a_day():
    """A two-hour demo earning +0.1% annualizes to +54%, which nobody projected.

    Arithmetically fine, honest over almost no span, and it would be the largest
    number on the vault page. Below a day the answer is "not enough history".
    """
    series = _series([1_000_000 + i * 20 for i in range(12)], step_minutes=10)  # ~2h
    summary = summarize(VAULT, series)

    assert summary.return_pct is not None, "a plain return over two hours is fine"
    assert summary.annualized_return_pct is None
    assert summary.volatility_pct is None
    assert summary.risk_adjusted_return is None


def test_annualization_appears_once_the_span_is_long_enough():
    series = _series([1_000_000 + i * 40 for i in range(30)], step_minutes=90)  # ~44h
    summary = summarize(VAULT, series)
    assert summary.annualized_return_pct is not None
    assert summary.volatility_pct is not None


# ── the arithmetic ────────────────────────────────────────────────────────


def test_return_is_measured_first_to_last():
    summary = summarize(VAULT, _series([1_000_000, 1_005_000, 1_010_000]))
    assert summary.return_pct == pytest.approx(0.01)


def test_max_drawdown_is_peak_to_trough_not_first_to_worst():
    """A vault that climbs then falls has a drawdown measured from its peak.

    Measuring from the first observation would report 0% for a vault that went
    1.00 -> 1.20 -> 1.05, which is a 12.5% fall a depositor certainly felt.
    """
    summary = summarize(VAULT, _series([1_000_000, 1_200_000, 1_050_000]))
    assert summary.max_drawdown_pct == pytest.approx(0.125)


def test_a_monotonic_series_has_no_drawdown():
    summary = summarize(VAULT, _series([1_000_000, 1_001_000, 1_002_000]))
    assert summary.max_drawdown_pct == pytest.approx(0.0)


def test_a_point_with_no_share_price_is_skipped_not_treated_as_zero():
    """Before the first deposit, total_supply is 0 and a share has no price.

    Reading that as 0.0 would put a -100% leg at the front of every curve.
    """
    unpriced = PerformancePoint(
        timestamp=_T0, total_assets="0", total_supply="0", block_number=1
    )
    summary = summarize(VAULT, [unpriced, *_series([1_000_000, 1_010_000])])
    assert summary.observations == 3
    assert summary.return_pct == pytest.approx(0.01)


def test_the_24h_return_does_not_reach_outside_its_window():
    """An event-spaced series often has nothing near the window edge.

    Anchoring on the nearest point *outside* the window would report a
    seven-day move as a one-day move, which is the wrong number in the most
    flattering possible direction.
    """
    old = _point(0, 1_000_000)
    recent = [
        PerformancePoint(
            timestamp=_T0 + timedelta(days=7, hours=h),
            block_number=49_100_000 + h,
            share_price=str(1_100_000 + h * 100),
            total_assets="1",
            total_supply="1",
        )
        for h in range(4)
    ]
    summary = summarize(VAULT, [old, *recent])

    assert summary.return_pct == pytest.approx(0.1003, abs=1e-4), "since inception"
    assert summary.return_24h_pct == pytest.approx(0.000272, abs=1e-5), "last day only"


# ── store ─────────────────────────────────────────────────────────────────


def test_the_same_block_is_never_recorded_twice(tmp_path):
    """Ticks, the sampler and the backfill all observe the same chain.

    On a pinned fork a quiet minute produces no new block, so without this the
    series fills with identical points and every volatility figure derived from
    it is wrong in a way that looks entirely plausible.
    """
    store = PerformanceStore(tmp_path)
    point = _point(0, 1_000_000, block=49_000_123)

    assert store.append(VAULT, point) is True
    assert store.append(VAULT, point) is False
    assert len(store.read(VAULT)) == 1


def test_reads_are_chronological_even_when_writes_were_not(tmp_path):
    """The backfill appends historical points after live ones already exist.

    File order is therefore not chronological, and a chart drawn from raw file
    order zig-zags backwards through time.
    """
    store = PerformanceStore(tmp_path)
    store.append(VAULT, _point(120, 1_002_000, block=3))
    store.append(VAULT, _point(0, 1_000_000, block=1))
    store.append(VAULT, _point(60, 1_001_000, block=2))

    timestamps = [p.timestamp for p in store.read(VAULT)]
    assert timestamps == sorted(timestamps)


def test_a_corrupt_line_costs_one_point_not_the_whole_curve(tmp_path):
    store = PerformanceStore(tmp_path)
    store.append(VAULT, _point(0, 1_000_000, block=1))
    path = tmp_path / "performance" / f"{VAULT.lower()}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"timestamp": "not-a-date"\n')
    store.append(VAULT, _point(60, 1_001_000, block=2))

    assert len(store.read(VAULT)) == 2


def test_extend_reports_only_what_was_new(tmp_path):
    store = PerformanceStore(tmp_path)
    first = [_point(i * 60, 1_000_000 + i, block=i) for i in range(3)]
    assert store.extend(VAULT, first) == 3
    assert store.extend(VAULT, first) == 0
    assert store.extend(VAULT, [*first, _point(999, 1_009_999, block=99)]) == 1


# ── windows ───────────────────────────────────────────────────────────────


def test_an_empty_window_falls_back_rather_than_reporting_no_history():
    """A vault whose last trade was two days ago still has a history.

    Returning [] for `?window=24h` would render "no data" on a vault with a
    perfectly good month of curve behind it.
    """
    stale = [
        PerformancePoint(
            timestamp=datetime.now(UTC) - timedelta(days=5, hours=h),
            block_number=100 + h,
            share_price=str(1_000_000 + h),
            total_assets="1",
            total_supply="1",
        )
        for h in range(6)
    ]
    assert window_points(stale, "24h"), "a stale vault must not render as empty"


def test_an_unknown_window_is_treated_as_all():
    series = _series([1_000_000, 1_001_000])
    assert len(window_points(series, "nonsense")) == 2


# ── recorder ──────────────────────────────────────────────────────────────


def test_a_holding_with_no_valuation_is_dropped_rather_than_guessed():
    """An unvalued holding cannot be a slice of a pie chart.

    Dropping it is visible — the stack falls short of total_assets — while
    guessing a value would put a confidently wrong slice on the page.
    """
    state = VaultState(
        address=VAULT,
        asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        total_assets="1000000",
        total_supply="1000000000000000000",
        # 1.0 as a `VaultState.share_price` is 1e18, NOT 1000000. This fixture
        # originally carried the base-asset value and the test passed, which is
        # how the two conventions got confused in the first place.
        share_price="1000000000000000000",
        block_number=42,
        holdings=[
            Holding(
                token="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                symbol="USDC",
                balance="1000000",
                value_in_asset="1000000",
            ),
            Holding(
                token="0x4200000000000000000000000000000000000006",
                symbol="WETH",
                balance="500000000000000000",
                # no value_in_asset — the feed was unreadable this block
            ),
        ],
    )

    point = point_from_state(state)
    assert point.allocation == [AllocationSlice(symbol="USDC", value_in_asset="1000000")]
    assert point.share_price == "1000000", "rescaled from the 1e18 ratio to asset units"
    assert point.block_number == 42


# ── the 1e12 bug ──────────────────────────────────────────────────────────


def test_a_live_state_is_rescaled_to_base_asset_units():
    """The bug that put a return of 99,965,347,459,900% on the vault page.

    `VaultState.share_price` is a dimensionless ratio × 1e18; a
    `PerformancePoint.share_price` is assets per share in BASE-ASSET decimals.
    They differ by exactly 10^12 for a 6-decimal asset, and the recorder used to
    copy the first through as the second — with a comment asserting it already
    carried the right convention.

    The result was a series where backfilled points read `999653` and live
    points read `999653474600000000`, on a vault that was down 3 bps.
    """
    state = VaultState(
        address=VAULT,
        asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        total_assets="9996534746",
        total_supply="10000000000000000000000",
        asset_decimals=6,
        # What Web3VaultClient actually produces: 0.999653 × 1e18.
        share_price="999653474600000000",
        block_number=49_078_011,
    )
    assert point_from_state(state).share_price == "999653"


def test_no_shares_issued_stays_absent_rather_than_becoming_zero():
    """Before the first deposit a share of nothing has no price. Zero would be
    a claim that the share is worthless, and it would put a -100% leg at the
    front of every curve."""
    state = VaultState(
        address=VAULT,
        asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        total_assets="0",
        total_supply="0",
        share_price=None,
    )
    assert point_from_state(state).share_price is None


def test_a_scale_mismatch_is_refused_rather_than_reported_as_a_return():
    """The backstop, kept because the series has three independent writers.

    A share price is O(1) and slow. A 10^12 step between two observations is a
    unit mistake every time, and reporting it as a return is far worse than
    dropping the points before it.
    """
    mixed = [
        _point(0, 1_000_000, block=1),
        _point(60, 999_653, block=2),
        # A live point written with the old, wrong scale.
        _point(120, 999_653_474_600_000_000, block=3),
        _point(180, 999_653_474_600_000_000, block=4),
    ]
    summary = summarize(VAULT, mixed)

    assert summary.return_pct == pytest.approx(0.0), "the consistent tail, not the jump"
    assert summary.return_pct is not None
    assert abs(summary.return_pct) < 1.0, (
        "a scale mismatch reached the summary as a return"
    )
