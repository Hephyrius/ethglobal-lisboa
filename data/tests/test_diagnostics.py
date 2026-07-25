"""Every message a source emits must read as a diagnosis.

Wave 1 fixed *which channel* a message goes to (`errors` vs `notes`). Wave 2
fixes *what it says*. The reader is a model deciding whether to move capital,
and the difference between

    messari: ConnectionError: [Errno 11001] getaddrinfo failed
    messari - uniswap-v3: the host could not be resolved (DNS) - the other
    facts in this snapshot are unaffected

is whether it can tell a dead data layer from one protocol being unreachable.

The last test here is the one that keeps this true: it drives every registered
source into failure and asserts the shape, so a bare `self.note(str(exc))`
added next month fails the suite rather than quietly regressing the feed.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from curator_schema.models import Fact

from curator_data.diagnostics import (
    describe_age,
    explain_exception,
    is_rate_limited,
)
from curator_data.ports import BaseSource


class Recorder(BaseSource):
    """A source that only exists to capture what `diagnose` produces."""

    key = "recorder"

    async def fetch(self, assets: list[str]) -> list[Fact]:
        return []


# ── the three-part shape ──────────────────────────────────────────────────


def test_a_diagnosis_names_who_what_and_so_what():
    source = Recorder()
    source.diagnose("uniswap-v3", "no response within 6s", "skipped so it does not delay others")

    assert source.drain_notes() == [
        "uniswap-v3: no response within 6s - skipped so it does not delay others"
    ]


def test_a_diagnosis_can_be_context_rather_than_failure():
    """The split that stopped 35 of 36 ticks opening with a false alarm."""
    source = Recorder()
    source.diagnose("USDC", "it is the quote token here", "priced by the oracle instead",
                    failure=False)

    assert source.drain_notes() == []
    assert len(source.drain_remarks()) == 1


def test_draining_clears_so_a_note_is_not_reported_twice():
    source = Recorder()
    source.diagnose("x", "y", "z")
    assert len(source.drain_notes()) == 1
    assert source.drain_notes() == []


def test_messages_stay_ascii_so_a_windows_console_can_print_them():
    """The CLI prints these; cp1252 turns an em dash into a mojibake box."""
    source = Recorder()
    source.diagnose("uniswap-v3", "no response within 6s", "skipped")
    source.drain_notes()[0].encode("ascii")


# ── translating failures into observations ────────────────────────────────


def test_a_dns_failure_says_dns_rather_than_errno():
    assert "DNS" in explain_exception(httpx.ConnectError("[Errno 11001] getaddrinfo failed"))


def test_a_refused_connection_is_distinguished_from_dns():
    assert "refused" in explain_exception(httpx.ConnectError("connection refused"))


def test_a_timeout_says_it_timed_out():
    assert "timed out" in explain_exception(httpx.TimeoutException("slow"))
    assert "deadline" in explain_exception(asyncio.TimeoutError())


def test_an_http_error_keeps_the_status_code():
    response = httpx.Response(502, request=httpx.Request("GET", "https://example.test"))
    exc = httpx.HTTPStatusError("bad gateway", request=response.request, response=response)
    assert "502" in explain_exception(exc)


def test_an_unrecognised_failure_falls_back_to_its_message():
    """Better a specific KeyError than a vague 'an error occurred'."""
    assert explain_exception(RuntimeError("GRAPH_API_KEY is not set")) == "GRAPH_API_KEY is not set"
    assert explain_exception(KeyError()) == "KeyError"


# ── rate limiting is not a rejected credential ────────────────────────────


@pytest.mark.parametrize(
    "status,body",
    [(429, ""), (403, "rate limit exceeded"), (200, "Too Many Requests"), (503, "throttled")],
)
def test_rate_limits_are_recognised(status, body):
    assert is_rate_limited(status, body)


@pytest.mark.parametrize("status,body", [(401, "invalid token"), (403, "forbidden"), (500, "")])
def test_other_refusals_are_not_mistaken_for_rate_limits(status, body):
    """One clears by itself; the other needs an operator. Same message for
    both teaches the agent nothing about either."""
    assert not is_rate_limited(status, body)


# ── staleness keeps its number ────────────────────────────────────────────


@pytest.mark.parametrize(
    "seconds,expected",
    [(45, "45s"), (600, "10m"), (88_200, "24.5h"), (259_200, "3.0d")],
)
def test_ages_are_human_but_keep_the_figure(seconds, expected):
    """'stale' is an opinion; '24.5h old' is a fact the agent can weigh."""
    assert describe_age(seconds) == expected


def test_the_wave_2_target_message_is_reproducible():
    """The plan quotes this verbatim as the shape to hit."""
    source = Recorder()
    source.diagnose("USDC", f"price is {describe_age(88_200)} old",
                    "the agent should treat it as stale")
    assert source.drain_notes() == [
        "USDC: price is 24.5h old - the agent should treat it as stale"
    ]


# ── the guarantee that keeps this from eroding ────────────────────────────


async def test_every_source_emits_diagnoses_when_it_fails():
    """Drive each registered source into failure and check the shape.

    A bare `self.note(str(exc))` added later fails here rather than quietly
    reaching the decision feed. Sources that raise instead of noting are fine —
    the registry translates those through `explain_exception`.
    """
    from curator_data.config import Settings
    from curator_data.sources import SOURCE_FACTORIES

    # No credentials, no network: every source fails in some way.
    settings = Settings(rpc_url="http://127.0.0.1:1")
    offenders: list[str] = []

    for key, factory in SOURCE_FACTORIES.items():
        try:
            source = factory(settings)
        except Exception:  # noqa: BLE001 - construction failure is the registry's problem
            continue
        try:
            await asyncio.wait_for(source.fetch(["USDC", "WETH"]), timeout=20)
        except Exception:  # noqa: BLE001 - raising is a legal way to fail
            pass
        finally:
            messages = source.drain_notes() + source.drain_remarks()
            close = getattr(source, "close", None)
            if close:
                await close()

        for message in messages:
            # "subject: observation - consequence"
            if ": " not in message or " - " not in message:
                offenders.append(f"{key}: {message!r} (not three parts)")
            try:
                # Found a real one: defillama used an em dash, which renders as
                # a mojibake box on a cp1252 Windows console mid-demo.
                message.encode("ascii")
            except UnicodeEncodeError:
                offenders.append(f"{key}: {message!r} (non-ASCII)")

    assert offenders == [], (
        "these messages are not three-part ASCII diagnoses "
        "(subject: observation - consequence). Use self.diagnose(...):\n  "
        + "\n  ".join(offenders)
    )
