"""CLI and live-verification behaviour.

These assert the operational contract rather than formatting: exit codes are
what a script or a teammate's terminal actually acts on, and `verify-live`
exists to be trusted when it says the demo path is live.
"""

from __future__ import annotations

import json

import pytest

from curator_data.cli import main
from curator_data.config import Settings
from curator_data.verify import CheckResult, report, summarise, verify_live

NO_CREDS = Settings()


# ── exit codes ────────────────────────────────────────────────────────────


def test_sources_lists_both_shipped_sources(capsys):
    assert main(["sources"]) == 0
    out = capsys.readouterr().out
    assert "messari" in out and "token_api" in out
    # The extension instruction is part of the output on purpose.
    assert "SOURCE_FACTORIES" in out


def test_sources_json_is_machine_readable(capsys):
    assert main(["sources", "--json"]) == 0
    entries = json.loads(capsys.readouterr().out)
    assert {e["key"] for e in entries} == {"messari", "token_api"}


def test_protocols_prints_the_config_table(capsys):
    assert main(["protocols"]) == 0
    out = capsys.readouterr().out
    assert "aave-v3" in out and "moonwell" in out
    assert "one Protocol(...) line" in out


def test_verify_live_exits_nonzero_without_credentials(capsys):
    """The command exists to prove live data; 'not checked' is not proof."""
    assert main(["verify-live"]) == 1
    assert "GRAPH_API_KEY" in capsys.readouterr().out


def test_snapshot_exits_nonzero_when_it_produced_no_facts(capsys):
    assert main(["snapshot", "--assets", "USDC"]) == 1


def test_snapshot_json_is_schema_valid_even_when_degraded(capsys):
    """Another lane must be able to consume this output unconditionally."""
    from curator_schema.models import MarketSnapshot

    main(["snapshot", "--assets", "USDC", "--json"])
    snapshot = MarketSnapshot.model_validate(json.loads(capsys.readouterr().out))
    assert snapshot.errors  # degraded
    assert snapshot.taken_at  # but still well-formed


def test_snapshot_reports_degradation_visibly(capsys):
    main(["snapshot", "--assets", "USDC"])
    assert "Degraded" in capsys.readouterr().out


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit):
        main(["nonsense"])


# ── verification logic ────────────────────────────────────────────────────


async def test_verify_skips_protocols_rather_than_repeating_one_missing_key():
    """N identical 'no API key' failures bury the single line that matters."""
    results = await verify_live(NO_CREDS)

    credential_failures = [r for r in results if r.name.endswith("API_KEY") and not r.ok]
    assert len(credential_failures) == 2

    protocol_checks = [r for r in results if "(" in r.name]
    assert protocol_checks and all(r.skipped for r in protocol_checks)


async def test_verify_names_an_unknown_protocol_rather_than_passing_vacuously():
    results = await verify_live(NO_CREDS, only="not-a-protocol")
    assert any("no protocol named" in r.detail for r in results)


def test_summarise_does_not_count_skips_as_passes():
    results = [
        CheckResult("a", ok=True, detail=""),
        CheckResult("b", ok=False, detail=""),
        CheckResult("c", ok=False, detail="", skipped=True),
    ]
    assert summarise(results) == (1, 1, 1)


def test_report_is_ascii_only():
    """Windows consoles are cp1252; a stray em dash becomes a mojibake box."""
    text = report([CheckResult("x", ok=False, detail="missing")])
    text.encode("ascii")  # raises if not


def test_report_states_the_submission_gate_when_something_failed():
    text = report([CheckResult("x", ok=False, detail="missing")])
    assert "submission gate" in text
