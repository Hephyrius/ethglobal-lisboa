"""Settings resolution.

The test that matters here is the drift one. `Settings` declares defaults as
dataclass fields, and `_build()` resolves them from the environment — if
`_build()` repeats the defaults as literals, the two can disagree, and which one
applies depends on how the object was made. Tests construct `Settings(...)`
directly; the running server goes through `settings()`. A stale literal therefore
produces a green suite and a differently-configured process.

That is not hypothetical: `MODEL_NAME` sat on a 14B in `_build()` after the field
default moved to the 3B, and it was only caught by noticing that `GET /health`
reported a model nobody had configured.
"""

from __future__ import annotations

import pytest

from agent.config import REPO_ROOT, Settings, settings

#: Every field `_build()` resolves from the environment with a default.
DEFAULTED_FIELDS = [
    "mode",
    "model_backend",
    "model_name",
    "ollama_base_url",
    "vllm_base_url",
    "model_timeout_s",
    "max_validation_retries",
    "rpc_url",
    "chain_id",
    "state_dir",
    "cors_origins",
]


@pytest.fixture
def clean_env(monkeypatch):
    """No AGENT_*/MODEL_* overrides, so `_build()` must fall back to defaults."""
    for name in [
        "AGENT_MODE",
        "AGENT_MODEL_BACKEND",
        "MODEL_NAME",
        "OLLAMA_BASE_URL",
        "VLLM_BASE_URL",
        "AGENT_MODEL_TIMEOUT_S",
        "AGENT_MAX_VALIDATION_RETRIES",
        "ANVIL_RPC_URL",
        "CHAIN_ID",
        "AGENT_STATE_DIR",
        "AGENT_CORS_ORIGINS",
        "AGENT_DATA_REGISTRY",
        "AGENT_VENUE_REGISTRY",
    ]:
        monkeypatch.delenv(name, raising=False)
    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.mark.parametrize("field", DEFAULTED_FIELDS)
def test_field_defaults_and_resolved_defaults_agree(clean_env, field):
    """One source of truth for every default.

    With nothing set in the environment, `settings()` must produce exactly what
    `Settings()` declares — otherwise the suite and the server are configured
    differently and nothing says so.
    """
    assert getattr(settings(), field) == getattr(Settings(), field)


# ── the settings that decide whether a demo works ─────────────────────────


def test_the_default_mode_is_fixture(clean_env):
    """Fixture mode needs no model, no chain and no other lane, so an
    unconfigured checkout still serves Lane E."""
    assert settings().mode == "fixture"
    assert not settings().is_live


def test_the_default_model_is_sized_for_cpu_inference(clean_env):
    """A 14B at Q4 streams ~9GB per token on a machine with no GPU, which is
    minutes per tick. Measured with `agent.bench`; see the build log."""
    assert "3b" in settings().model_name.lower()


def test_no_provider_refs_by_default(clean_env):
    """Unset means fixtures, which is what makes a fresh clone work."""
    assert settings().data_registry_ref is None
    assert settings().venue_registry_ref is None


def test_the_dapp_origin_is_allowed_by_default(clean_env):
    assert "http://localhost:3000" in settings().cors_origins


def test_state_lives_under_the_repo_not_an_absolute_path(clean_env):
    """No absolute paths in committed config — macOS takes over at 10:00."""
    assert settings().state_dir.is_relative_to(REPO_ROOT)


# ── environment overrides ─────────────────────────────────────────────────


def test_the_environment_wins_over_the_default(clean_env, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "llama3.2:3b")
    settings.cache_clear()
    assert settings().model_name == "llama3.2:3b"


def test_an_unknown_mode_falls_back_to_fixture(clean_env, monkeypatch):
    """A typo must not silently arm live mode on a vault with a real key."""
    monkeypatch.setenv("AGENT_MODE", "livee")
    settings.cache_clear()
    assert settings().mode == "fixture"


def test_a_non_numeric_override_falls_back_rather_than_crashing(clean_env, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_VALIDATION_RETRIES", "three")
    settings.cache_clear()
    assert settings().max_validation_retries == Settings().max_validation_retries


def test_cors_origins_parse_as_a_comma_separated_list(clean_env, monkeypatch):
    monkeypatch.setenv("AGENT_CORS_ORIGINS", "http://a.test, http://b.test ")
    settings.cache_clear()
    assert settings().cors_origins == ["http://a.test", "http://b.test"]


def test_the_model_base_url_follows_the_backend(clean_env, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_BACKEND", "vllm")
    settings.cache_clear()
    assert settings().model_base_url() == settings().vllm_base_url
