# Publishing `curator-mcp` to PyPI

The MCP server is a submission deliverable for The Graph's Track 1, whose stated criteria include
**Reusability & completeness (25%)** and whose defining requirement is *"reusable tooling or
infrastructure … not a single end-user app."* A server only we can run does not meet that.

**Current release: `curator-data` 0.4.0, `curator-mcp` 0.4.0, on `curator-schema` 0.2.0.** Verified
from a clean Python 3.10 machine with no clone: 10 sources, 4 tools, and the Wave 3 sanitiser live.
What follows is the release process for the next version.

> ### `curator-schema` is no longer built or published by default — and that makes the check stronger
>
> `./data/publish.sh` used to build and upload all three. It now builds only the two Lane C owns,
> and `--include-schema` opts into the third. Two reasons, the second of which is the one that
> actually caught a bug:
>
> 1. **It is Lane F's release decision, not ours.** Mid-wave the repo's schema version routinely runs
>    ahead of what its owner has chosen to publish — at the time of the 0.4.0 release the repo said
>    `0.3.0` while PyPI served `0.2.0`. A version number is permanent, so spending one on a state
>    nobody signed off is not a decision to take on someone's behalf.
> 2. **With no schema wheel in `dist/`, `--find-links` must resolve `curator-schema` from PyPI.** So
>    the dry run now proves our floor is satisfiable *by what is actually served*. That is precisely
>    the blind spot that shipped a broken `0.3.0`: building every sibling locally hid a stale
>    published version behind a fresh local wheel, and the release looked fine right up until a judge
>    would have run it.
>
> If the floor genuinely cannot be met from the index, the resolve fails with a message saying so and
> naming `--include-schema` — rather than silently publishing another lane's work.

**Earlier releases.** 0.2.0 (first publish, 2026-07-25) · 0.3.0 (broken: `curator-schema` content
changed without a version bump, so PyPI served stale bytes) · 0.3.1 (repaired — the missing piece was
a **version floor**, not the bump; an unpinned dependency is not "always latest", it is "whatever the
resolver already has a reason to prefer").

---

## It also installs from a clone, without PyPI

Still true and still useful for anyone modifying it. The blocker reported in the phase 2 plan §6 —
`uv pip install ./data/curator_mcp` failing with *"Because curator-data was not found in the package
registry … unsatisfiable"* — was fixed before publishing, and remains fixed.

`data/curator_mcp/pyproject.toml` now carries relative `[tool.uv.sources]` for its two siblings, so
a clone resolves them locally. Verified in a clean Python 3.10 venv outside the repo:

```bash
uv pip install ./data/curator_mcp      # exit 0
python -c "import asyncio; from curator_mcp.server import build_server; \
           print(sorted(t.name for t in asyncio.run(build_server().list_tools())))"
# ['compare_protocols', 'get_market_yields', 'get_token_price', 'list_markets']
```

Those entries are **inert once the packages exist on PyPI** — a registry version satisfies the
requirement first — and they match the root workspace's `editable = true`, without which `uv sync`
fails with *"Requirements contain conflicting URLs for package curator-data"*.

## Publishing makes `uvx curator-mcp` work for someone who has never seen the repo

That is the version worth having: a judge pasting our MCP config into their own client, with no
clone.

### The short version

```bash
./data/publish.sh                 # build + verify, uploads nothing — safe to run now
./data/publish.sh --publish       # build, verify, confirm, then upload
```

The dry run is the default deliberately. It builds the two Lane C distributions and proves they install
from wheels alone in a clean 3.10 venv — the check that matters, because a PyPI version number can
never be re-uploaded. `--publish` additionally requires `UV_PUBLISH_TOKEN` and prompts before
uploading, since `curator-schema` belongs to Wave 0 rather than Lane C.

The manual equivalents are below, for anyone who would rather see each step.

### 1. Build

```bash
uv build --out-dir dist packages/schema/python   # curator-schema
uv build --out-dir dist data                     # curator-data
uv build --out-dir dist data/curator_mcp         # curator-mcp
```

Verified — all three produce a wheel and an sdist:

```
curator_schema-0.1.0-py3-none-any.whl   curator_schema-0.1.0.tar.gz
curator_data-0.2.0-py3-none-any.whl     curator_data-0.2.0.tar.gz
curator_mcp-0.2.0-py3-none-any.whl      curator_mcp-0.2.0.tar.gz
```

### 2. Prove the wheels stand alone *before* uploading

This is the step that catches a broken dependency chain while it is still free to fix:

```bash
uv venv --python 3.10 /tmp/wheelcheck/.venv
uv pip install --python /tmp/wheelcheck/.venv --find-links dist curator-mcp
```

**Verified passing.** Resolving from `--find-links` alone proves the wheel metadata carries real
dependency names rather than the local path sources — path sources are a uv resolution hint and are
deliberately not baked into wheels.

### 3. Upload — bottom of the dependency chain first

Order matters: each upload must be able to resolve the one below it.

```bash
export UV_PUBLISH_TOKEN=pypi-...            # from https://pypi.org/manage/account/token/

uv publish --token "$UV_PUBLISH_TOKEN" dist/curator_schema-*
uv publish --token "$UV_PUBLISH_TOKEN" dist/curator_data-*
uv publish --token "$UV_PUBLISH_TOKEN" dist/curator_mcp-*
```

Then confirm the thing we actually claim in `SKILL.md`:

```bash
uvx curator-mcp        # from a machine that has never seen this repo
```

### Names

`curator-mcp`, `curator-data` and `curator-schema` are ours as of 2026-07-25. Remember a version
number on PyPI is **permanent** — 0.2.0 can never be re-uploaded, only superseded.

> **`curator-schema` belongs to Wave 0**, not to Lane C. It needs no edit to publish — its metadata
> is already valid — but the decision to publish it is not Lane C's to take alone. It is the bottom
> of the chain, so `curator-data` cannot be published without it.

### Test first, if you want to be careful

```bash
uv publish --publish-url https://test.pypi.org/legacy/ --token "$UV_TEST_TOKEN" dist/*
```

Note that a version number on PyPI is **permanent** — `0.2.0` can never be re-uploaded, only
superseded by `0.2.1`. Get the wheel-only check in step 2 passing first.

---

## Why the version numbers moved to 0.2.0

Not changelog hygiene. **uv caches built wheels by name and version**, so rebuilding `0.1.0` after
adding modules serves the stale wheel and fails with a confusing `ModuleNotFoundError: No module
named 'curator_data.sources.feeds'`. Hit during this work; `--no-cache` confirmed the diagnosis.
Bump the version whenever the package contents change.

## Checklist before publishing

- [x] `LICENSE` present at repo root (MIT), matching what both `pyproject.toml`s declare
- [x] `readme` set on every package, so PyPI shows a description
- [x] Classifiers and keywords set
- [x] `requires-python = ">=3.10"` — the MCP SDK's floor, verified by installing on 3.10
- [x] Wheels install from `--find-links` with no repo present
- [x] `curator-mcp` exposes the `curator-mcp` console script
- [x] **PyPI token** — supplied; published 2026-07-25
- [ ] Repo public (a stated requirement of every Graph track anyway)
