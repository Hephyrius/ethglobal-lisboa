"""Mapping domain failures to HTTP status codes.

Without this, a vault the harness has never heard of surfaces to the dApp as an
opaque `500 Internal Server Error`, which tells Lane E nothing and looks like a
crash. These are ordinary, expected conditions — a user opening a bookmarked
vault, a live deployment before Lane A's factory address is configured — and they
deserve status codes that say so.

Deliberately narrow. Only conditions with a genuinely correct HTTP meaning are
mapped; anything unrecognised stays a 500, because converting real bugs into tidy
4xx responses hides them.

Note this is about *transport* failures. A decision cycle that held, was rejected
or reverted on-chain is **not** an error — `POST /tick` returns 200 with an
`AgentAction` describing it (see `agent/loop/cycle.py`). Nothing here interferes
with that.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..mandate.amend import AmendmentRejected
from ..mandate.store import MandateNotFound

__all__ = ["register_exception_handlers"]

log = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(MandateNotFound)
    async def _mandate_not_found(_: Request, exc: MandateNotFound) -> JSONResponse:
        """404 — this harness has no mandate for that vault.

        Expected whenever the dApp opens a vault that was deployed by a different
        harness instance, or before genesis has run. Not a server fault.
        """
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AmendmentRejected)
    async def _amendment_rejected(_: Request, exc: AmendmentRejected) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(_: Request, exc: NotImplementedError) -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _misconfigured(request: Request, exc: ValueError) -> JSONResponse:
        """503 — the harness is running but not configured to do this yet.

        Covers live mode without `AGENT_PRIVATE_KEY` or `VAULT_FACTORY_ADDRESS`.
        The message names the missing setting, because "500" during a demo sends
        someone reading tracebacks instead of reading `.env`.
        """
        log.warning("%s %s refused: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=503, content={"detail": f"harness not configured: {exc}"}
        )
