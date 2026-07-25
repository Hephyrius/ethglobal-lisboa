"""Environment-driven settings for the harness.

Everything machine-specific arrives through the environment, and every path is
derived from the repository root discovered relative to this file. Nothing
absolute, nothing Windows-shaped: the same tree runs unchanged in WSL and on the
macOS box that takes over at 10:00 (master plan §3).

The two settings worth understanding are `mode` and the two provider refs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

__all__ = ["Settings", "settings", "REPO_ROOT", "FIXTURES_DIR"]

#: agent/config.py -> agent/ -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "packages" / "schema" / "fixtures"

load_dotenv(REPO_ROOT / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_or_none(name: str) -> str | None:
    return _env(name) or None


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = _env(name)
    return [part.strip() for part in raw.split(",") if part.strip()] if raw else default


@dataclass(frozen=True)
class Settings:
    """Resolved configuration. Built once per process via `settings()`."""

    #: "fixture" serves the golden fixtures and never touches the network or a
    #: chain; "live" wires the real model, data registry, venues and RPC. The
    #: mode swaps *dependencies* only — route handlers are identical in both, so
    #: the endpoint Lane E integrated against in hour 2 is the one that runs at
    #: the demo. There is no fixture-only endpoint to migrate off later.
    mode: str = "fixture"

    # ── model layer ───────────────────────────────────────────────────────
    model_backend: str = "ollama"
    model_name: str = "qwen2.5:14b-instruct"
    ollama_base_url: str = "http://localhost:11434/v1"
    vllm_base_url: str = "http://localhost:8000/v1"
    model_timeout_s: float = 120.0
    #: Attempts at a schema-valid, mandate-legal decision before the cycle is
    #: recorded as `rejected`. Three is enough to recover from the malformed
    #: output small open models produce, and few enough that a model which
    #: cannot follow the schema fails fast instead of burning the tick.
    max_validation_retries: int = 3

    # ── other lanes, resolved late (never imported at module scope) ───────
    #: "module:attribute" pointing at Lane C's DataSourceRegistry, e.g.
    #: "data.registry:registry". Unset -> the fixture registry.
    data_registry_ref: str | None = None
    #: "module:attribute" pointing at Lane D's venue registry, e.g.
    #: "venues:registry". Unset -> the fixture venue.
    venue_registry_ref: str | None = None

    # ── chain ─────────────────────────────────────────────────────────────
    rpc_url: str = "http://localhost:8540"
    agent_private_key: str | None = None
    factory_address: str | None = None
    chain_id: int = 8453

    # ── process ───────────────────────────────────────────────────────────
    state_dir: Path = field(default_factory=lambda: REPO_ROOT / ".agent-state")
    #: Lane E's dev server. The dApp calls this API from the browser, so without
    #: CORS every frozen route fails with an opaque preflight error rather than a
    #: useful one (cross-lane request #4 from Lane E).
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def model_base_url(self) -> str:
        return self.vllm_base_url if self.model_backend == "vllm" else self.ollama_base_url


def _build() -> Settings:
    mode = _env("AGENT_MODE", "fixture").lower()
    if mode not in {"fixture", "live"}:
        mode = "fixture"
    return Settings(
        mode=mode,
        model_backend=_env("AGENT_MODEL_BACKEND", "ollama").lower(),
        model_name=_env("MODEL_NAME", "qwen2.5:14b-instruct"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        vllm_base_url=_env("VLLM_BASE_URL", "http://localhost:8000/v1"),
        model_timeout_s=_env_float("AGENT_MODEL_TIMEOUT_S", 120.0),
        max_validation_retries=_env_int("AGENT_MAX_VALIDATION_RETRIES", 3),
        data_registry_ref=_env_or_none("AGENT_DATA_REGISTRY"),
        venue_registry_ref=_env_or_none("AGENT_VENUE_REGISTRY"),
        rpc_url=_env("ANVIL_RPC_URL", "http://localhost:8540"),
        agent_private_key=_env_or_none("AGENT_PRIVATE_KEY"),
        factory_address=_env_or_none("VAULT_FACTORY_ADDRESS"),
        chain_id=_env_int("CHAIN_ID", 8453),
        state_dir=(
            Path(_env("AGENT_STATE_DIR")) if _env("AGENT_STATE_DIR") else REPO_ROOT / ".agent-state"
        ),
        cors_origins=_env_list(
            "AGENT_CORS_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"]
        ),
    )


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Process-wide settings. Cached so the environment is read once.

    Tests that need a different configuration call `settings.cache_clear()`
    after patching the environment.
    """
    return _build()
