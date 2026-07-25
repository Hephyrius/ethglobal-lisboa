"""Backend registration table — one line per backend.

Adding a model provider means writing one file next to these and adding one
entry to `BACKENDS`. Nothing in the decision loop changes, because everything
downstream depends on `curator_schema.ports.ModelBackend` rather than on a
concrete client. Same extension shape the data layer uses for sources and the
venue layer uses for execution paths.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...config import Settings
from .ollama import OllamaBackend
from .scripted import ScriptedBackend
from .vllm import VLLMBackend

__all__ = ["BACKENDS", "build_backend", "OllamaBackend", "VLLMBackend", "ScriptedBackend"]


def _ollama(settings: Settings) -> OllamaBackend:
    return OllamaBackend(
        base_url=settings.ollama_base_url,
        model=settings.model_name,
        timeout=settings.model_timeout_s,
    )


def _vllm(settings: Settings) -> VLLMBackend:
    return VLLMBackend(
        base_url=settings.vllm_base_url,
        model=settings.model_name,
        timeout=settings.model_timeout_s,
    )


#: name -> factory. `scripted` is deliberately absent: it needs responses that
#: only a caller can supply, so it is constructed directly rather than selected
#: by configuration. Nothing should be able to put a canned model in front of a
#: live vault by setting an environment variable.
BACKENDS: dict[str, Callable[[Settings], Any]] = {
    "ollama": _ollama,
    "vllm": _vllm,
}


def build_backend(settings: Settings):
    """The configured `ModelBackend`.

    Falls back to Ollama on an unknown name — the local-first default — with the
    mistake logged rather than crashing a tick.
    """
    factory = BACKENDS.get(settings.model_backend)
    if factory is None:
        import logging

        logging.getLogger(__name__).warning(
            "unknown AGENT_MODEL_BACKEND %r; known backends are %s. Using ollama.",
            settings.model_backend,
            ", ".join(sorted(BACKENDS)),
        )
        factory = _ollama
    return factory(settings)
