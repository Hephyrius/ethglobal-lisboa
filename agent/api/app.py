"""FastAPI application factory.

Serves the routes frozen in master plan §8 and mirrored in
`packages/schema/ts/src/index.ts`. Lane E consumes these; they do not change
shape between fixture and live mode.

Run it:

    uv run uvicorn agent.api.app:app --reload --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings, settings
from .deps import data_resolution, get_settings, venue_resolution
from .errors import register_exception_handlers
from .routes import archetypes, genesis, portfolio, vault, venues
from .schemas import HealthResponse

__all__ = ["create_app", "app"]

log = logging.getLogger(__name__)

DESCRIPTION = """
The agent harness behind an autonomous ERC-4626 vault curator.

`AGENT_MODE=fixture` (the default) serves the golden fixtures from
`packages/schema/fixtures/` with no network access; `AGENT_MODE=live` runs the
real decision loop. The routes are identical in both — check `GET /health` to
see which providers actually resolved.
"""


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or settings()

    app = FastAPI(
        title="Agentic Vault Curator — agent harness",
        version="0.1.0",
        description=DESCRIPTION,
    )

    # The dApp calls this API from the browser, so without CORS every frozen
    # route fails preflight with an error that names none of the real cause
    # (cross-lane request #4 from Lane E). Origins are configurable because the
    # macOS handoff at 10:00 may not use port 3000.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(genesis.router)
    app.include_router(vault.router)
    # Not one of the frozen Wave 0 routes. The dApp could answer "how is this
    # vault doing?" and had no way to answer "how am I doing?", which is the
    # first question a depositor with money in more than one vault asks.
    app.include_router(portfolio.router)
    app.include_router(venues.router)
    app.include_router(archetypes.router)

    @app.get(
        "/health",
        response_model=HealthResponse,
        response_model_exclude_none=True,
        tags=["meta"],
    )
    async def health() -> HealthResponse:
        """Liveness plus, more usefully, *what each seam actually resolved to*.

        A live run quietly serving fixture numbers because Lane C's registry
        failed to import is the failure this endpoint exists to make obvious.
        """
        cfg = get_settings()
        data = data_resolution()
        venues = venue_resolution()

        # Only asked in live mode: fixture mode never calls a model, and a
        # 5-second probe on every health check would be pure cost.
        model_ok: bool | None = None
        if cfg.is_live:
            model_ok = await _model_available(cfg)

        degraded = cfg.is_live and (
            data.is_fixture or venues.is_fixture or model_ok is not True
        )
        return HealthResponse(
            status="degraded" if degraded else "ok",
            mode=cfg.mode,
            data_registry=data.label,
            venue_registry=venues.label,
            # `resolved_model_name()`, not `model_name` (#100). The two are
            # different namespaces: `.env` sets MODEL_NAME to an Ollama tag, so
            # a Grok run reported `grok:qwen2.5:3b-instruct-q4_K_M` — a 3B that
            # is authoring nothing. This is the endpoint anyone checking "what
            # is actually running" reaches for, including us at the rehearsal,
            # so it is the one place that must not answer with the wrong model.
            model_backend=f"{cfg.model_backend}:{cfg.resolved_model_name()}",
            model_reachable=model_ok,
        )

    return app


async def _model_available(config: Settings) -> bool | None:
    """Is the *configured model* actually served? None if we could not ask.

    `False` here is the failure worth catching before a demo: Ollama running
    with nothing pulled looks perfectly healthy to a plain ping, right up until
    the first tick fails with `model not found`.
    """
    try:
        from ..model.backends import build_backend

        backend = build_backend(config)
        checker = getattr(backend, "has_model", None)
        return await checker() if callable(checker) else None
    except Exception as exc:  # noqa: BLE001 - health must never be the thing that breaks
        log.warning("model availability check failed: %s", exc)
        return None


app = create_app()
