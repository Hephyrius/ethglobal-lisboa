"""Shared test fixtures for Lane B.

The important one is `assert_valid`. It checks payloads against the **JSON
Schema files**, not the pydantic models — `packages/schema/*.json` is the source
of truth and the pydantic mirror is a view of it. Validating against pydantic
alone would only prove the harness agrees with itself; validating against the
JSON proves it agrees with the contract Lane E's zod mirror was written from.

The schemas cross-reference each other by relative URI (`agent-action` pulls in
`allocation-decision`, `execution-plan` and `market-snapshot`), so they are
loaded into a `referencing` Registry keyed by `$id`. Without it `jsonschema`
would try to resolve those refs over the network.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from agent.config import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "packages" / "schema"


@pytest.fixture(scope="session")
def schema_registry() -> Registry:
    registry = Registry()
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


@pytest.fixture(scope="session")
def assert_valid(schema_registry: Registry) -> Callable[[str, Any], None]:
    """`assert_valid("vault-state", payload)` — raises with every error listed."""

    def _assert(schema_name: str, payload: Any) -> None:
        path = SCHEMA_DIR / f"{schema_name}.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, registry=schema_registry)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            detail = "\n".join(
                f"  at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                for e in errors
            )
            raise AssertionError(f"payload does not satisfy {schema_name}.schema.json:\n{detail}")

    return _assert


@pytest.fixture(scope="session")
def client():
    """TestClient over the app in fixture mode.

    Mode is forced rather than inherited: a developer with `AGENT_MODE=live` in
    their `.env` should still get a hermetic test run.
    """
    os.environ["AGENT_MODE"] = "fixture"
    os.environ.pop("AGENT_DATA_REGISTRY", None)
    os.environ.pop("AGENT_VENUE_REGISTRY", None)

    from fastapi.testclient import TestClient

    from agent.api import deps
    from agent.api.app import create_app

    deps.reset()
    with TestClient(create_app()) as test_client:
        yield test_client
    deps.reset()


def iter_json_values(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Flatten a decoded JSON document to (path, scalar) pairs.

    Used by the wire-format assertions, which have to inspect every leaf rather
    than the handful of fields a given test happens to know about.
    """
    found: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(iter_json_values(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(iter_json_values(value, f"{path}/{index}"))
    else:
        found.append((path or "<root>", node))
    return found
