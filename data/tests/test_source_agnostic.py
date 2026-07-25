"""The invariant that keeps this layer from ossifying around one provider.

The master build plan lists "data layer ossifies around The Graph" as a known
risk, and the frozen schema says no field may be named after a provider. Those
are easy to honour on day one and easy to erode at 3am under deadline, so they
are asserted rather than trusted.

The rule: **the registry and the shared types must not mention any provider.**
Provider names belong in `sources/` (where the adapters live), in the protocol
and token tables (which are configuration), and nowhere else.
"""

from __future__ import annotations

import inspect
import pathlib

from curator_data import facts, ports, queries, registry
from curator_data.registry import Registry

#: Names that would indicate provider-specific logic leaking upward. "graph"
#: is matched as a whole word to avoid false hits on "graphql" in a docstring.
PROVIDER_WORDS = ("messari", "thegraph", "subgraph", "chainlink", "pyth", "defillama", "uniswap")

#: Modules that must stay provider-neutral. `sources/` is deliberately absent —
#: that package is where provider knowledge is supposed to live.
NEUTRAL_MODULES = (registry, facts, ports, queries)


def _strip_docs(source: str) -> str:
    """Executable source only.

    Docstrings legitimately mention providers as examples ("adding Chainlink is
    one line"), and that documentation is worth keeping — it is how the next
    person learns where the extension point is. What must not exist is
    provider-specific *behaviour*.
    """
    out, in_doc, delim = [], False, ""
    for line in source.splitlines():
        stripped = line.strip()
        if not in_doc:
            for d in ('"""', "'''"):
                if stripped.startswith(d):
                    # A one-line docstring opens and closes on the same line.
                    if not (len(stripped) > 5 and stripped.endswith(d)):
                        in_doc, delim = True, d
                    break
            else:
                out.append(line.split("#", 1)[0])
        elif delim in stripped:
            in_doc = False
    return "\n".join(out).lower()


def test_neutral_modules_contain_no_provider_specific_logic():
    for module in NEUTRAL_MODULES:
        code = _strip_docs(inspect.getsource(module))
        for word in PROVIDER_WORDS:
            assert word not in code, (
                f"{module.__name__} mentions '{word}' in executable code. Provider "
                f"knowledge belongs in curator_data/sources/, not in the registry or "
                f"the shared types — otherwise adding a provider stops being one line."
            )


def test_the_registry_has_no_hardcoded_source_list():
    """A Registry built with no factories knows about nothing at all."""
    assert Registry({}).available() == []


def test_registry_signature_names_no_provider():
    signature = str(inspect.signature(Registry.snapshot))
    assert "source_keys" in signature
    for word in PROVIDER_WORDS:
        assert word not in signature.lower()


def test_the_registration_table_is_the_only_place_sources_are_listed():
    """Adding a source must mean editing exactly one shipped file.

    If a second module ever enumerates source keys, the "one line" claim
    quietly becomes "two lines, and you will find the second one in production".
    """
    package = pathlib.Path(inspect.getfile(registry)).parent
    offenders = []
    for path in package.rglob("*.py"):
        if path.parent.name == "sources":
            continue
        # Docstrings stripped: a usage example naming both sources is
        # documentation, while executable code naming both is a second copy of
        # the registration table.
        text = _strip_docs(path.read_text(encoding="utf-8"))
        if '"messari"' in text and '"token_api"' in text:
            offenders.append(path.name)
    assert offenders == [], f"source keys duplicated outside sources/: {offenders}"
