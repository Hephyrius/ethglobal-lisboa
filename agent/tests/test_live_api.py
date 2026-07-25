"""The API in live mode — the shapes Lane E gets once fixtures are switched off.

Runs the real services with a scripted model and no chain, so it needs no
network, no credential and no GPU. What it checks is the part fixture mode
cannot: that live mode returns the *same* shapes, and that ordinary conditions
Lane E will hit — an unknown vault, an unconfigured deployment — come back as
readable status codes rather than opaque 500s.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agent import fixtures

UNKNOWN = "0x9999999999999999999999999999999999999999"


@pytest.fixture
def live(tmp_path, monkeypatch):
    """A live-mode client whose model is scripted and whose chain is the stub."""
    monkeypatch.setenv("AGENT_MODE", "live")
    monkeypatch.setenv("AGENT_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("AGENT_DATA_REGISTRY", raising=False)
    monkeypatch.delenv("AGENT_VENUE_REGISTRY", raising=False)
    monkeypatch.delenv("AGENT_PRIVATE_KEY", raising=False)

    from agent.api import deps
    from agent.api.app import create_app

    deps.reset()
    app = create_app()
    with TestClient(app) as client:
        yield client
    deps.reset()


def _script(client, responses):
    """Swap the live service's model for a scripted one.

    Reaching into the service is deliberate and confined to this helper: the
    alternative is a test that needs a running Ollama, which would make the
    suite unrunnable on the build machine and on the macOS handoff.
    """
    from agent.api.deps import get_vault_service
    from agent.loop.engine import LlmDecisionEngine
    from agent.model.backends.scripted import ScriptedBackend

    service = get_vault_service()
    service._cycle._engine = LlmDecisionEngine(ScriptedBackend(responses), max_attempts=2)
    return service


# ── ordinary conditions must not look like crashes ────────────────────────


def test_an_unknown_vault_mandate_is_a_404(live):
    """Expected whenever the dApp opens a vault this harness did not deploy."""
    response = live.get(f"/vault/{UNKNOWN}/mandate")
    assert response.status_code == 404
    assert "mandate" in response.json()["detail"]


def test_an_unknown_vault_has_an_empty_decision_feed(live):
    response = live.get(f"/vault/{UNKNOWN}/decisions")
    assert response.status_code == 200
    assert response.json() == []


def test_ticking_an_unknown_vault_returns_a_failed_action_not_an_error(live):
    """`POST /tick` reports outcomes in the feed, never as a transport error."""
    response = live.post(f"/vault/{UNKNOWN}/tick")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "no mandate" in body["error"]


# ── genesis writes state the vault routes then read ───────────────────────


def test_genesis_finalize_makes_the_vault_readable(live, assert_valid):
    mandate = json.loads(fixtures.mandate().model_dump_json(exclude_none=True))

    created = live.post("/genesis/finalize", json={"mandate": mandate})
    assert created.status_code == 200, created.text
    vault = created.json()["vault"]

    fetched = live.get(f"/vault/{vault}/mandate")
    assert fetched.status_code == 200
    assert_valid("mandate", fetched.json())
    assert fetched.json()["name"] == mandate["name"]


def test_a_live_tick_is_schema_valid_and_journaled(live, assert_valid):
    mandate = json.loads(fixtures.mandate().model_dump_json(exclude_none=True))
    vault = live.post("/genesis/finalize", json={"mandate": mandate}).json()["vault"]

    _script(live, [fixtures.allocation_decision().model_dump_json(exclude_none=True)])

    action = live.post(f"/vault/{vault}/tick").json()
    assert_valid("agent-action", action)
    assert action["status"] == "executed"
    assert action["tx_hashes"]

    feed = live.get(f"/vault/{vault}/decisions").json()
    assert len(feed) == 1
    assert_valid("agent-action", feed[0])
    assert feed[0]["id"] == action["id"]


def test_a_live_rejection_is_schema_valid_and_kept(live, assert_valid):
    """The record that proves validation stopped something."""
    mandate = json.loads(fixtures.mandate().model_dump_json(exclude_none=True))
    vault = live.post("/genesis/finalize", json={"mandate": mandate}).json()["vault"]

    _script(live, ["not json at all", "still not json"])

    action = live.post(f"/vault/{vault}/tick").json()
    assert_valid("agent-action", action)
    assert action["status"] == "rejected"
    assert "plan" not in action
    assert action["tx_hashes"] == []
    assert live.get(f"/vault/{vault}/decisions").json()[0]["status"] == "rejected"


# ── the wire-format guarantees hold in live mode too ──────────────────────


def test_live_responses_carry_no_nulls_and_utc_timestamps(live):
    """The two zod traps are mode-independent; fixture-only coverage would miss
    a live-only field."""
    import re

    from .conftest import iter_json_values

    iso_z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
    looks_like_dt = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    mandate = json.loads(fixtures.mandate().model_dump_json(exclude_none=True))
    vault = live.post("/genesis/finalize", json={"mandate": mandate}).json()["vault"]
    _script(live, [fixtures.allocation_decision().model_dump_json(exclude_none=True)])

    for label, body in {
        "tick": live.post(f"/vault/{vault}/tick").json(),
        "decisions": live.get(f"/vault/{vault}/decisions").json(),
        "mandate": live.get(f"/vault/{vault}/mandate").json(),
        "state": live.get(f"/vault/{vault}/state").json(),
        "health": live.get("/health").json(),
    }.items():
        for path, value in iter_json_values(body):
            assert value is not None, f"{label}{path} is null — zod .optional() rejects null"
            if isinstance(value, str) and looks_like_dt.match(value):
                assert iso_z.match(value), f"{label}{path} = {value!r} is not UTC-with-Z"
