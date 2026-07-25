"""Grok as the default backend, and the fallback that keeps a fresh clone working.

The operator's rule, in one sentence: **Grok when there is a key, local Ollama
when there is not.** Everything here pins one half of that, because the failure
mode of getting it wrong is silent — a run that quietly used a different model
than the one you think produced the decisions in the feed.
"""

from __future__ import annotations

from agent.config import Settings
from agent.model.backends import BACKENDS, GrokBackend, build_backend


def test_a_key_selects_grok_on_the_cheapest_model_per_decision():
    """Cheapest *per decision*, which is not the cheapest per token.

    `grok-build-0.1` is the per-token floor ($1.00/M vs $1.25/M) and costs 14x
    more per decision, because it is a reasoning model billing 10,195 reasoning
    tokens to emit 267 — and it rejects `reasoning_effort`, so it cannot be
    turned down. Measured, not reasoned about; the table is in the module
    docstring of `agent/model/backends/grok.py`.

    This asserts the *unit* as much as the value: anyone re-picking this model
    on per-token price alone makes each tick 14x dearer and 26x slower.
    """
    backend = build_backend(Settings(model_backend="grok", xai_api_key="k"))
    assert isinstance(backend, GrokBackend)
    assert backend.model == "grok-4.20-0309-non-reasoning"


def test_no_key_falls_back_to_ollama_rather_than_failing():
    """A missing key is the expected state on a fresh clone, not a misconfiguration.

    Anyone who never signed up for xAI must still get a working stack, so this
    degrades rather than raising.
    """
    backend = build_backend(Settings(model_backend="grok", xai_api_key=None))
    assert backend.name == "ollama"
    assert backend.model == Settings().model_name


def test_an_explicit_backend_is_never_silently_substituted():
    """Naming a backend wins over the credential heuristic.

    This matters for the model bake-off: substituting a different model than the
    one someone named is how a benchmark reports the wrong winner.
    """
    assert build_backend(Settings(model_backend="ollama", xai_api_key="k")).name == "ollama"


def test_an_unknown_backend_still_degrades_to_ollama():
    assert build_backend(Settings(model_backend="nonsense")).name == "ollama"


def test_grok_is_registered_like_every_other_backend():
    assert "grok" in BACKENDS


# ── the two namespaces ────────────────────────────────────────────────────


def test_xai_model_is_a_separate_field_from_model_name():
    """`.env` already sets MODEL_NAME to an Ollama tag.

    One variable serving both backends would send `qwen2.5:3b-instruct-q4_K_M`
    to xAI and 404 on the first tick. The two model namespaces are disjoint, so
    they get two fields — this asserts they have not been merged.
    """
    settings = Settings()
    assert settings.model_name != settings.xai_model
    assert settings.resolved_model_name() == settings.model_name

    grok = Settings(model_backend="grok")
    assert grok.resolved_model_name() == grok.xai_model


def test_the_base_url_follows_the_backend():
    assert Settings(model_backend="grok").model_base_url() == "https://api.x.ai/v1"
    assert Settings(model_backend="vllm").model_base_url() == Settings().vllm_base_url
    assert Settings(model_backend="ollama").model_base_url() == Settings().ollama_base_url


def test_grok_asks_for_schema_guided_decoding_when_given_a_schema():
    """Verified live against grok-build-0.1 before this was written.

    xAI accepts `strict: true` json_schema, which puts this backend in vLLM's
    class rather than Ollama's. Pinned because a provider quietly dropping an
    unsupported `response_format` would give a false sense of enforcement — the
    exact reason Ollama's hint ignores the schema argument instead of passing it.
    """
    from agent.model.backends.grok import _guided_json_hint

    schema = {"type": "object", "properties": {"action": {"type": "string"}}}
    hint = _guided_json_hint(schema)
    assert hint["response_format"]["type"] == "json_schema"
    assert hint["response_format"]["json_schema"]["strict"] is True
    assert hint["response_format"]["json_schema"]["schema"] is schema

    # No schema is still a JSON-syntax request, never an unconstrained one.
    assert _guided_json_hint(None)["response_format"] == {"type": "json_object"}
