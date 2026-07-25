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
from .routes import genesis, vault
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
        degraded = cfg.is_live and (data.is_fixture or venues.is_fixture)
        return HealthResponse(
            status="degraded" if degraded else "ok",
            mode=cfg.mode,
            data_registry=data.label,
            venue_registry=venues.label,
            model_backend=cfg.model_backend,
        )

    return app


app = create_app()
