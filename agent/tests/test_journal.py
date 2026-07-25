"""The decision journal — the store behind `GET /vault/{addr}/decisions`.

Worth testing on its own because its failure modes are quiet ones. A journal
that silently drops history, or that throws on a truncated final line, breaks the
demo feed without breaking anything that would show up in a cycle test.

The truncation case is not hypothetical: the journal is append-only text, a tick
writes one line, and a process killed mid-write leaves a partial record. Costing
the vault its entire visible history over one bad byte would be the worst
possible response.
"""

from __future__ import annotations

import pytest

from agent import fixtures
from agent.clock import utcnow
from agent.loop.store import ActionJournal

VAULT = "0x1111111111111111111111111111111111111111"


def _action(index: int, *, status: str = "executed", minutes_ago: int = 0):
    from datetime import timedelta

    golden = fixtures.agent_action()
    return golden.model_copy(
        update={
            "id": f"act_{index:06d}",
            "vault": VAULT,
            "status": status,
            "timestamp": utcnow() - timedelta(minutes=minutes_ago),
        }
    )


def test_an_empty_journal_reads_as_empty_not_an_error(tmp_path):
    """A vault that has never ticked is normal, not exceptional."""
    journal = ActionJournal(tmp_path)
    assert journal.recent(VAULT, 10) == []
    assert journal.count(VAULT) == 0
    assert journal.last_executed(VAULT) is None


def test_actions_round_trip_through_the_journal(tmp_path):
    journal = ActionJournal(tmp_path)
    original = _action(1)
    journal.append(original)

    (restored,) = journal.recent(VAULT, 10)
    assert restored.id == original.id
    assert restored.status == "executed"
    assert restored.decision is not None
    assert restored.tx_hashes == original.tx_hashes
    # tz-awareness must survive the disk round trip, or the wire format breaks.
    assert restored.timestamp.tzinfo is not None


def test_the_feed_is_newest_first_regardless_of_write_order(tmp_path):
    journal = ActionJournal(tmp_path)
    journal.append(_action(1, minutes_ago=5))
    journal.append(_action(2, minutes_ago=90))
    journal.append(_action(3, minutes_ago=45))

    ids = [a.id for a in journal.recent(VAULT, 10)]
    assert ids == ["act_000001", "act_000003", "act_000002"]


def test_limit_takes_the_newest_not_the_first_written(tmp_path):
    journal = ActionJournal(tmp_path)
    for index, age in enumerate([120, 90, 60, 30, 1], start=1):
        journal.append(_action(index, minutes_ago=age))

    assert [a.id for a in journal.recent(VAULT, 2)] == ["act_000005", "act_000004"]


def test_a_truncated_final_line_costs_one_record_not_the_history(tmp_path):
    """A process killed mid-write leaves a partial line. Everything before it
    is still a valid record of what the agent did, and must still be served."""
    journal = ActionJournal(tmp_path)
    journal.append(_action(1, minutes_ago=30))
    journal.append(_action(2, minutes_ago=20))

    path = tmp_path / "actions" / f"{VAULT.lower()}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "act_000003", "vault": "0x111')  # killed mid-write

    surviving = journal.recent(VAULT, 10)
    assert len(surviving) == 2
    assert {a.id for a in surviving} == {"act_000001", "act_000002"}


def test_a_record_that_no_longer_matches_the_schema_is_skipped(tmp_path):
    """Schema-invalid history must not take down the whole feed either."""
    journal = ActionJournal(tmp_path)
    journal.append(_action(1))

    path = tmp_path / "actions" / f"{VAULT.lower()}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "act_x", "vault": "not-an-address", "status": "executed"}\n')

    assert [a.id for a in journal.recent(VAULT, 10)] == ["act_000001"]


def test_blank_lines_are_ignored(tmp_path):
    journal = ActionJournal(tmp_path)
    journal.append(_action(1))
    path = tmp_path / "actions" / f"{VAULT.lower()}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")

    assert journal.count(VAULT) == 1


# ── the cooldown depends on this being exactly right ──────────────────────


@pytest.mark.parametrize("status", ["held", "rejected", "failed", "pending"])
def test_only_executed_cycles_count_as_the_last_trade(tmp_path, status):
    """`last_executed` drives the mandate's rebalance cooldown.

    Counting a hold or a rejection as a trade would lock the agent out of the
    market for an hour because it declined to act — the exact opposite of what
    the constraint is for.
    """
    journal = ActionJournal(tmp_path)
    journal.append(_action(1, status=status, minutes_ago=1))
    assert journal.last_executed(VAULT) is None


def test_last_executed_finds_the_most_recent_trade_not_the_most_recent_action(tmp_path):
    journal = ActionJournal(tmp_path)
    journal.append(_action(1, status="executed", minutes_ago=90))
    journal.append(_action(2, status="executed", minutes_ago=40))
    journal.append(_action(3, status="held", minutes_ago=1))

    last = journal.last_executed(VAULT)
    assert last is not None and last.id == "act_000002"


# ── vaults are isolated from each other ───────────────────────────────────


def test_two_vaults_do_not_share_a_journal(tmp_path):
    other = "0x2222222222222222222222222222222222222222"
    journal = ActionJournal(tmp_path)
    journal.append(_action(1))
    journal.append(_action(2).model_copy(update={"vault": other}))

    assert journal.count(VAULT) == 1
    assert journal.count(other) == 1
    assert journal.recent(other, 5)[0].vault == other


def test_a_checksummed_address_reads_the_same_journal_as_a_lowercase_one(tmp_path):
    """Addresses are case-insensitive on-chain but case-sensitive on disk, and
    the dApp may send either form."""
    journal = ActionJournal(tmp_path)
    journal.append(_action(1))

    mixed = "0x1111111111111111111111111111111111111111".upper().replace("0X", "0x")
    assert journal.count(mixed) == 1
