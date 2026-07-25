"""`GET /venues` serves Lane D's manifest verbatim (cross-lane #73).

Lane D built the capability manifest and Lane E's venue strip needs it, but
nothing served it over HTTP, so the browser could only see the bare venue keys
`/genesis/sources` returns.

The tests that matter here are not about the happy path — one call, one array —
but about the two ways this route could quietly break the lane it exists to
unblock:

**Re-modelling the payload.** The manifest is Lane D's own shape and explicitly
*not* part of the frozen interface, which is what lets them extend it without a
schema request. A pydantic `response_model` here would strip any key this lane
did not anticipate, so the next field Lane D ships would vanish between two lanes
that both believed they had delivered it. Pinned with a ref that returns a key
nothing in this repo has ever heard of.

**Turning an outage into a false claim.** `[]` means "there are no venues", which
would render as an empty strip. A 503 is a thing Lane E can branch on, and they
already built the degraded state for it.
"""

from __future__ import annotations

import pytest

MANIFEST_KEYS = {"key", "role", "summary", "intents", "custody", "available"}


@pytest.fixture
def route(client):
    return lambda: client.get("/venues")


# ── what it serves ────────────────────────────────────────────────────────


def test_the_manifest_is_served_as_an_unwrapped_array(route):
    """Lane E asked for "the manifest array, unwrapped" and parses it directly —
    an envelope object would break them at the first index."""
    response = route()

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and body


def test_every_entry_carries_the_fields_lane_e_named(route):
    """#61's published shape. Missing one is a broken venue strip, not a
    cosmetic gap."""
    for entry in route().json():
        missing = MANIFEST_KEYS - set(entry)
        assert not missing, f"{entry.get('key')} is missing {sorted(missing)}"


def test_the_four_registered_venues_are_all_present(route):
    """Lane D's Wave 2 registry. If this shrinks, a venue became unreachable to
    the UI — which is the failure that hid the fully-built Aave venue for an
    entire wave."""
    keys = {entry["key"] for entry in route().json()}

    assert {"uniswap", "aqua", "aave", "morpho"} <= keys


def test_an_unavailable_venue_is_listed_rather_than_hidden(route):
    """A venue missing a credential must say *why* it cannot be used. Filtering
    it out makes a configuration problem look like a venue that does not
    exist."""
    for entry in route().json():
        if not entry["available"]:
            assert entry.get("unavailable_reason"), entry["key"]


# ── the two ways it could quietly break Lane E ────────────────────────────


def test_a_field_this_lane_has_never_heard_of_survives_the_round_trip(client, monkeypatch):
    """**The reason there is no `response_model`.** Lane D can extend the
    manifest without a schema request; if this route validated against a shape
    written here, their next field would be dropped silently."""
    from agent.api import deps

    def manifest():
        return [{"key": "hypothetical", "a_field_added_next_wave": {"nested": [1, 2]}}]

    monkeypatch.setattr(
        "agent.api.routes.venues.resolve_ref", lambda ref: manifest(), raising=True
    )
    deps.reset()

    body = client.get("/venues").json()

    assert body == [{"key": "hypothetical", "a_field_added_next_wave": {"nested": [1, 2]}}]


def test_an_unresolvable_manifest_is_a_503_naming_the_ref(client, monkeypatch):
    """Not `[]`. "There are no venues" is a different and false claim, and it
    would render as an empty strip rather than the degraded state Lane E built."""

    def boom(ref):
        raise ImportError("no module named 'venues'")

    monkeypatch.setattr("agent.api.routes.venues.resolve_ref", boom, raising=True)

    response = client.get("/venues")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "venues:manifest" in detail
    assert "GET /genesis/sources" in detail, "the 503 should say what still works"


def test_a_ref_pointing_at_the_wrong_thing_says_so(client, monkeypatch):
    """A misconfiguration that resolves is worse than one that does not: it
    would serve whatever it happened to find."""
    monkeypatch.setattr(
        "agent.api.routes.venues.resolve_ref", lambda ref: {"not": "a list"}, raising=True
    )

    response = client.get("/venues")

    assert response.status_code == 503
    assert "expected a list" in response.json()["detail"]


def test_the_manifest_ref_is_overridable(client):
    """Configured like every other cross-lane seam, so a fork of Lane D's
    package does not need a code change here."""
    from agent.config import Settings

    assert Settings().venue_manifest_ref == "venues:manifest"
