"""Fact construction: units, provenance and id stability."""

from __future__ import annotations

import pytest

from curator_data.facts import FactBuilder, dedupe_ids, subject_slug


def test_apy_from_percent_divides_by_one_hundred():
    builder = FactBuilder("messari")
    fact = builder.apy_from_percent(builder.subject(protocol="aave-v3", market="USDC"), 4.32)
    assert fact.value == 0.0432
    assert fact.unit == "apy_fraction"


def test_apy_from_fraction_passes_through():
    builder = FactBuilder("chainlink")
    fact = builder.apy_from_fraction(builder.subject(token="USDC"), 0.0432)
    assert fact.value == 0.0432


def test_a_builder_cannot_emit_a_fact_attributed_to_another_source():
    builder = FactBuilder("messari")
    fact = builder.usd("tvl", builder.subject(protocol="aave-v3"), 1.0)
    assert fact.source == "messari"


def test_builder_requires_a_source_key():
    with pytest.raises(ValueError, match="provenance"):
        FactBuilder("")


def test_ids_are_deterministic_across_builders():
    """Same market, two snapshots, same id — so decisions can be diffed."""
    a = FactBuilder("messari")
    b = FactBuilder("messari")
    subject = a.subject(protocol="aave-v3", market="USDC")
    assert a.apy_from_percent(subject, 4.0).id == b.apy_from_percent(subject, 5.0).id


def test_ids_are_human_readable():
    builder = FactBuilder("messari")
    fact = builder.apy_from_percent(builder.subject(protocol="aave-v3", market="USDC"), 4.0)
    assert fact.id == "messari:yield:aave-v3/usdc"


def test_different_sources_never_collide():
    a = FactBuilder("messari")
    b = FactBuilder("chainlink")
    assert (
        a.usd("price", a.subject(token="WETH"), 1.0).id
        != b.usd("price", b.subject(token="WETH"), 1.0).id
    )


def test_dedupe_suffixes_later_duplicates_and_keeps_the_first_clean():
    builder = FactBuilder("messari")
    subject = builder.subject(protocol="aave-v3", market="USDC")
    facts = dedupe_ids([builder.usd("tvl", subject, 1.0), builder.usd("tvl", subject, 2.0)])
    assert [f.id for f in facts] == ["messari:tvl:aave-v3/usdc", "messari:tvl:aave-v3/usdc#1"]


def test_subject_slug_handles_pairs_and_empties():
    builder = FactBuilder("messari")
    assert subject_slug(builder.subject(pair=["USDC", "WETH"])) == "usdc-weth"
    assert subject_slug(builder.subject()) == "unknown"


def test_chain_defaults_onto_every_subject():
    builder = FactBuilder("messari", chain="base")
    assert builder.subject(token="USDC").chain == "base"
