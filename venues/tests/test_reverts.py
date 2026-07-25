"""Revert-selector decoding.

R5 failed for hours on `ContractCustomError 0x39d35496` with nobody able to
identify it — after hashing 426 local signatures, including all 307 in the
vendored 1inch packages. It was Uniswap's, not Aqua's. These tests pin the
decoder so that lookup is never repeated.
"""

from __future__ import annotations

import pytest

from venues.reverts import KNOWN_REVERTS, describe, explain, normalise


class TestTheOneThatCostHours:
    def test_it_identifies_the_r5_selector(self):
        known = explain("0x39d35496")
        assert known is not None
        assert known.signature == "V3TooLittleReceived()"

    def test_it_names_uniswap_not_aqua(self):
        """The wrong hypothesis was 'deployed 1inch bytecode we lack the source
        for'. Attributing it correctly is most of the value."""
        known = explain("0x39d35496")
        assert "Uniswap" in known.source
        assert "Aqua" not in known.source

    def test_it_distinguishes_fork_staleness_from_real_slippage(self):
        """Same selector, two very different causes and fixes — on mainnet
        re-quote, on a pinned fork widen the band or re-fork."""
        fix = explain("0x39d35496").fix
        assert "FORK" in fix.upper()
        assert "UNISWAP_SLIPPAGE_BPS" in fix


class TestDecoder:
    @pytest.mark.parametrize("form", ["0x39d35496", "39d35496", "0x39d354960000dead"])
    def test_it_accepts_the_forms_a_traceback_actually_contains(self, form):
        assert explain(form).signature == "V3TooLittleReceived()"

    def test_normalise_takes_the_selector_off_full_revert_data(self):
        assert normalise("0x39d35496deadbeef") == "39d35496"

    def test_every_entry_carries_a_fix_not_just_a_name(self):
        for entry in KNOWN_REVERTS.values():
            assert entry.fix and len(entry.fix) > 30, entry.signature
            assert entry.meaning
            assert entry.source

    def test_selectors_are_derived_from_signatures_never_typed_in(self):
        from eth_utils import keccak

        for selector, entry in KNOWN_REVERTS.items():
            assert keccak(text=entry.signature)[:4].hex() == selector

    def test_it_covers_all_four_protocols_a_plan_touches(self):
        sources = " ".join(e.source for e in KNOWN_REVERTS.values())
        for protocol in ("Uniswap", "Permit2", "Aqua", "CuratedVault"):
            assert protocol in sources


class TestUnknownSelectors:
    def test_an_unknown_selector_still_returns_guidance(self):
        """"Not one of ours" is itself a finding — it narrows the search rather
        than ending it."""
        text = describe("0xdeadbeef")
        assert "not a revert this lane" in text
        assert "eth_getCode" in text
        assert "4byte" in text

    def test_explain_returns_none_rather_than_guessing(self):
        assert explain("0xdeadbeef") is None
