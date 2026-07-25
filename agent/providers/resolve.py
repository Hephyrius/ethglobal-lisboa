"""Late binding to the other lanes.

The harness consumes Lane C's data registry and Lane D's venues, but Rule 7
forbids importing their internals and neither lane existed when this was
written. So `/agent` imports **no** other lane at module scope — ever. Providers
are named in configuration as `"module:attribute"` and imported on first use:

    AGENT_DATA_REGISTRY=data.registry:registry
    AGENT_VENUE_REGISTRY=venues:registry

Unset, or unimportable, or not matching the port -> the fixture provider, with a
warning. Three properties follow, all of them required:

- Lane C and Lane D landing costs this lane **zero code changes** — one env var
  each. That is the same extension mechanism the mandate uses for sources, one
  level up.
- A broken or half-built neighbouring lane degrades this one to fixtures instead
  of crashing it. During a 24-hour build with five instances pushing
  concurrently, an `ImportError` in someone else's tree must not take down the
  API that Lane E is developing against.
- `import agent` stays free of transitive lane imports, so the test suite runs
  with no other lane installed.

The runtime `isinstance` check against the Protocol is cheap insurance: a
provider that resolves but does not implement the port fails at startup with a
clear message rather than at the first tick with an `AttributeError`.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, TypeVar

__all__ = ["resolve_ref", "resolve_provider", "ProviderResolution"]

log = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderResolution:
    """What a seam resolved to, and why — surfaced on `GET /health`.

    Serving fixture numbers while believing you are live is the failure mode
    this exists to make visible.
    """

    __slots__ = ("provider", "ref", "is_fixture", "error")

    def __init__(
        self, provider: Any, ref: str, *, is_fixture: bool, error: str | None = None
    ) -> None:
        self.provider = provider
        self.ref = ref
        self.is_fixture = is_fixture
        self.error = error

    @property
    def label(self) -> str:
        # Name the ref that failed, not just the failure. "it fell back" is not
        # actionable at 3am; "it tried data.registry:registry and the module was
        # not found" is a fix.
        if self.error:
            return f"fixture (tried {self.ref}: {self.error})"
        return "fixture" if self.is_fixture else self.ref


def resolve_ref(ref: str) -> Any:
    """Import and return the object named by `"module:attribute"`.

    Raises ValueError on a malformed ref, ImportError if the module is missing,
    AttributeError if the attribute is not there. Callers that must not fail use
    `resolve_provider`.
    """
    if ":" not in ref:
        raise ValueError(
            f"provider ref {ref!r} must be 'module:attribute', e.g. 'data.registry:registry'"
        )
    module_name, _, attr = ref.partition(":")
    module = importlib.import_module(module_name)
    target = getattr(module, attr)
    # A lane may publish either a ready instance or a zero-argument factory.
    return target() if _is_factory(target) else target


def _is_factory(target: Any) -> bool:
    """True for a zero-argument callable that is not already an instance.

    Lets a lane publish either `registry = Registry()` or `def registry(): ...`
    without the consumer caring which — a small courtesy that avoids a
    cross-lane request over a naming detail.
    """
    if isinstance(target, type):
        return True
    import inspect

    if not inspect.isfunction(target):
        return False
    params = [
        p
        for p in inspect.signature(target).parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]
    return not params


def resolve_provider[T](
    ref: str | None, fallback: T, port: type | None = None, *, what: str = "provider"
) -> ProviderResolution:
    """Resolve `ref`, falling back to `fallback` on any failure.

    Never raises. A neighbouring lane that is missing or broken degrades this
    one to fixtures; it does not stop the API from serving.
    """
    if not ref:
        return ProviderResolution(fallback, "fixture", is_fixture=True)

    try:
        provider = resolve_ref(ref)
    except Exception as exc:  # noqa: BLE001 - any import-time failure degrades, never propagates
        log.warning("%s ref %r failed to resolve (%s); using fixtures", what, ref, exc)
        return ProviderResolution(
            fallback, ref, is_fixture=True, error=f"{type(exc).__name__}: {exc}"
        )

    if port is not None and not isinstance(provider, port):
        log.warning(
            "%s ref %r resolved to %r which does not satisfy %s; using fixtures",
            what,
            ref,
            type(provider).__name__,
            port.__name__,
        )
        return ProviderResolution(
            fallback, ref, is_fixture=True, error=f"does not satisfy {port.__name__}"
        )

    log.info("%s resolved to %s", what, ref)
    return ProviderResolution(provider, ref, is_fixture=False)
