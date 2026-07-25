"""Every frozen route returns a payload Lane E can actually parse.

Master plan §12 makes this a Lane B gate: *"FastAPI routes return schema-valid
payloads for every frozen route."* Schema-validity is necessary but not
sufficient — two wire-format details are legal JSON Schema and still break zod
in the browser, so they get their own tests:

- **datetimes must end in `Z`.** `z.string().datetime()` rejects `+02:00` and
  rejects a bare naive timestamp. `datetime.now()` on the Lisbon demo machine
  produces the former.
- **optional fields must be omitted, never `null`.** `z.optional()` accepts a
  missing key and rejects an explicit null.

Both would pass a Python-only test suite and fail live. Hence the assertions
over *every leaf* of every response rather than the fields a test remembers.
"""

from __future__ import annotations

import re

import pytest

from .conftest import iter_json_values

VAULT = "0x1111111111111111111111111111111111111111"

#: RFC 3339, UTC, `Z` suffix — the shape zod's `.datetime()` accepts.
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
#: Anything that looks like a timestamp, so the check cannot be dodged by a
#: field the test does not know the name of.
LOOKS_LIKE_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _every_response(client) -> dict[str, object]:
    """One call to each route, keyed by a readable label."""
    return {
        "GET /health": client.get("/health").json(),
        "GET /genesis/sources": client.get("/genesis/sources").json(),
        "POST /genesis/chat": client.post(
            "/genesis/chat", json={"messages": [{"role": "user", "content": "safe USDC yield"}]}
        ).json(),
        "GET /vault/state": client.get(f"/vault/{VAULT}/state").json(),
        "GET /vault/decisions": client.get(f"/vault/{VAULT}/decisions?limit=10").json(),
        "POST /vault/tick": client.post(f"/vault/{VAULT}/tick").json(),
        "GET /vault/mandate": client.get(f"/vault/{VAULT}/mandate").json(),
    }


# ── the frozen contract ───────────────────────────────────────────────────


def test_every_frozen_route_answers(client):
    for method, path in [
        ("get", "/health"),
        ("get", f"/vault/{VAULT}/state"),
        ("get", f"/vault/{VAULT}/decisions"),
        ("post", f"/vault/{VAULT}/tick"),
        ("get", f"/vault/{VAULT}/mandate"),
        ("get", "/genesis/sources"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 200, f"{method.upper()} {path} -> {response.text}"


def test_vault_state_matches_schema(client, assert_valid):
    body = client.get(f"/vault/{VAULT}/state").json()
    assert_valid("vault-state", body)
    # The route must describe the vault that was asked for, not the fixture's.
    assert body["address"] == VAULT


def test_decisions_match_schema_and_are_newest_first(client, assert_valid):
    body = client.get(f"/vault/{VAULT}/decisions?limit=10").json()
    assert isinstance(body, list) and body
    for action in body:
        assert_valid("agent-action", action)
        assert action["vault"] == VAULT
    timestamps = [a["timestamp"] for a in body]
    assert timestamps == sorted(timestamps, reverse=True), "feed must be newest first"


def test_decision_feed_covers_every_status(client):
    """Lane E has to render all five statuses; fixture mode must exercise them.

    If the feed only ever showed `executed`, the rejected and failed states
    would first appear during the live demo.
    """
    body = client.get(f"/vault/{VAULT}/decisions?limit=50").json()
    statuses = {action["status"] for action in body}
    assert {"executed", "held", "rejected", "failed"} <= statuses, statuses


def test_rejected_action_carries_no_plan_and_no_transactions(client):
    """The whole point of a rejection: nothing reached the chain."""
    body = client.get(f"/vault/{VAULT}/decisions?limit=50").json()
    rejected = [a for a in body if a["status"] == "rejected"]
    assert rejected
    for action in rejected:
        assert "plan" not in action
        assert action.get("tx_hashes", []) == []
        assert action.get("error"), "a rejection must say what was wrong"
        assert action["model"]["validation_retries"] > 0


def test_executed_action_carries_the_snapshot_it_reasoned_over(client):
    """Lane E draws data (with provenance) -> reasoning -> tx hash.

    That view is impossible if the snapshot never crosses the wire, and the
    golden fixture omits it.
    """
    action = client.post(f"/vault/{VAULT}/tick").json()
    assert action["snapshot"]["facts"], "no facts to attribute the decision to"
    assert {f["source"] for f in action["snapshot"]["facts"]}, "facts must carry provenance"
    cited = set(action["decision"]["facts_used"])
    available = {f["id"] for f in action["snapshot"]["facts"]}
    assert cited <= available, f"decision cites facts not in its snapshot: {cited - available}"


def test_tick_matches_schema(client, assert_valid):
    assert_valid("agent-action", client.post(f"/vault/{VAULT}/tick").json())


def test_mandate_matches_schema(client, assert_valid):
    assert_valid("mandate", client.get(f"/vault/{VAULT}/mandate").json())


def test_genesis_chat_draft_grows_with_the_conversation(client, assert_valid):
    """A draft that never changes lets the genesis UI ship without handling the
    case it actually faces: fields arriving progressively across turns."""
    messages: list[dict[str, str]] = []
    seen_field_counts: list[int] = []
    for turn in ("safe USDC yield", "allow WETH too, keep 20% cash", "use Messari and prices"):
        messages.append({"role": "user", "content": turn})
        body = client.post("/genesis/chat", json={"messages": messages}).json()
        assert body["reply"]
        seen_field_counts.append(len(body["mandate_draft"]))
        messages.append({"role": "assistant", "content": body["reply"]})

    assert seen_field_counts == sorted(seen_field_counts)
    assert seen_field_counts[-1] > seen_field_counts[0]
    # The final draft must be a legal full Mandate — otherwise "finalize what
    # you were shown" cannot work.
    final = client.post("/genesis/chat", json={"messages": messages}).json()["mandate_draft"]
    assert_valid("mandate", final)


def test_genesis_finalize_hash_is_real_and_deterministic(client):
    """The hash shown at genesis is the one committed on-chain, so it must be a
    real keccak over the mandate — not a placeholder — and stable."""
    mandate = client.get(f"/vault/{VAULT}/mandate").json()
    first = client.post("/genesis/finalize", json={"mandate": mandate}).json()
    second = client.post("/genesis/finalize", json={"mandate": mandate}).json()

    assert first["mandate_hash"] == second["mandate_hash"]
    assert re.fullmatch(r"0x[0-9a-f]{64}", first["mandate_hash"])
    assert re.fullmatch(r"0x[a-fA-F0-9]{40}", first["vault"])

    # A different mandate must hash differently, or the on-chain commitment
    # proves nothing about which mandate was deployed.
    altered = {**mandate, "objective": mandate["objective"] + " Also chase the highest APY."}
    third = client.post("/genesis/finalize", json={"mandate": altered}).json()
    assert third["mandate_hash"] != first["mandate_hash"]


def test_genesis_finalize_rejects_an_incomplete_mandate(client):
    """Deploying a vault against a half-finished draft is unrecoverable — the
    mandate is immutable to humans after genesis."""
    response = client.post("/genesis/finalize", json={"mandate": {"name": "half a plan"}})
    assert response.status_code == 422


def test_sources_are_offered_from_the_registry(client):
    body = client.get("/genesis/sources").json()
    assert body["sources"], "genesis cannot ask the user to grant an empty list"
    assert set(body["venues"]) <= {"uniswap", "aqua"}


# ── wire format: the two traps that only fail in the browser ──────────────


def test_all_datetimes_are_utc_with_a_z_suffix(client):
    for label, body in _every_response(client).items():
        for path, value in iter_json_values(body):
            if isinstance(value, str) and LOOKS_LIKE_DATETIME.match(value):
                assert ISO_Z.match(value), (
                    f"{label}{path} = {value!r} — zod's .datetime() rejects offsets and "
                    "naive timestamps; every datetime must be UTC with a Z suffix"
                )


def test_no_response_contains_a_json_null(client):
    """zod's `.optional()` accepts a missing key but rejects an explicit null.

    Every route sets `response_model_exclude_none=True`, so a null appearing
    anywhere means a route was added without it.
    """
    for label, body in _every_response(client).items():
        for path, value in iter_json_values(body):
            assert value is not None, (
                f"{label}{path} is null — zod .optional() rejects null; the route needs "
                "response_model_exclude_none=True"
            )


# ── operational behaviour ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad", ["not-an-address", "0x1234", "1111111111111111111111111111111111111111"]
)
def test_bad_vault_address_is_a_clean_422(client, bad):
    assert client.get(f"/vault/{bad}/state").status_code == 422


def test_cors_preflight_allows_the_dapp_origin(client):
    """Without this the dApp fails every route with an opaque preflight error
    (cross-lane request #4 from Lane E)."""
    response = client.options(
        f"/vault/{VAULT}/state",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_health_reports_which_providers_resolved(client):
    body = client.get("/health").json()
    assert body["mode"] == "fixture"
    # Fixture mode is a legitimate, non-degraded state; "degraded" is reserved
    # for a *live* run that silently fell back to fixtures.
    assert body["status"] == "ok"
    assert body["data_registry"] == "fixture"
    assert body["venue_registry"] == "fixture"


def test_decisions_limit_is_honoured(client):
    assert len(client.get(f"/vault/{VAULT}/decisions?limit=2").json()) == 2
    assert client.get(f"/vault/{VAULT}/decisions?limit=0").status_code == 422
