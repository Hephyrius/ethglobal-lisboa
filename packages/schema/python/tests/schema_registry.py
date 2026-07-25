"""Loads every JSON Schema in the package into one resolver.

Shared by `test_conformance.py` (fixtures) and `test_presets.py` (presets), so
both validate against the same registry rather than each building its own.

The registry has to be preloaded because `agent-action.schema.json` refs its
siblings by relative filename, which resolves against its own `$id`. Without
this, `jsonschema` tries to fetch `https://ethglobal-lisboa/...` over the
network — which fails, and fails slowly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

#: packages/schema/ — the JSON Schemas are the source of truth and live here.
SCHEMA_DIR = Path(__file__).resolve().parents[2]
FIXTURE_DIR = SCHEMA_DIR / "fixtures"
PRESET_DIR = SCHEMA_DIR / "presets"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def registry() -> Registry:
    """Every schema keyed by `$id`, so cross-schema `$ref`s resolve locally."""
    return Registry().with_resources(
        (
            load(path)["$id"],
            Resource.from_contents(load(path), default_specification=DRAFT202012),
        )
        for path in SCHEMA_DIR.glob("*.schema.json")
    )


def validator(schema_name: str) -> Draft202012Validator:
    return Draft202012Validator(load(SCHEMA_DIR / schema_name), registry=registry())


def errors_against(schema_name: str, instance: Any) -> str:
    """Every validation error, one per line, ready to drop into an assert.

    Reporting all of them rather than the first matters more than it looks:
    a mandate with three wrong fields cost three fix-run cycles when only the
    first was reported, and Lane B's schema-error reporting was fixed for the
    same reason.
    """
    found = sorted(validator(schema_name).iter_errors(instance), key=lambda e: list(e.path))
    return "\n".join(f"{list(e.path)}: {e.message}" for e in found)
