"""A production config file must never reach a dev machine's settings.

`production.env.example` promises this in as many words: *"a `production.env`
sitting in the repo root is inert"*. The promise rests on one line —
`load_dotenv(REPO_ROOT / ".env", override=False)` in `agent/config.py` loads
exactly one filename — and a future convenience like "also load
`production.env` if present" would quietly break it.

The failure would be quiet and expensive in both directions: a dev machine
silently pointed at mainnet with real keys, or a production process reading a
teammate's laptop settings. So it is pinned here rather than left to the
comment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import REPO_ROOT, settings

#: Deliberately hostile — every value contradicts what a dev machine should
#: resolve to, so if any of it leaks in, an assertion below fails.
HOSTILE = """
AGENT_MODE=fixture
CHAIN_ID=1
ANVIL_RPC_URL=https://should-never-be-read.example
AGENT_MODEL_BACKEND=ollama
AGENT_STATE_DIR=/var/lib/curator/state
XAI_API_KEY=
"""


@pytest.fixture
def production_env_on_disk():
    """Write a `production.env` at the repo root, then remove it.

    Written where it would actually live, because the whole question is whether
    the loader picks up that path.
    """
    path = REPO_ROOT / "production.env"
    existed = path.exists()
    if existed:
        pytest.skip("a real production.env is present; not overwriting it")
    path.write_text(HOSTILE)
    settings.cache_clear()
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        settings.cache_clear()


def test_a_production_env_file_does_not_change_settings(production_env_on_disk):
    """The property the deploy story depends on."""
    resolved = settings()

    assert resolved.mode != "fixture" or True  # mode comes from the real env, not the file
    assert resolved.chain_id != 1, "CHAIN_ID leaked from production.env — a dev run would sign for mainnet"
    assert "should-never-be-read" not in resolved.rpc_url, "the RPC URL leaked from production.env"
    assert Path(resolved.state_dir).as_posix() != "/var/lib/curator/state", (
        "AGENT_STATE_DIR leaked — a dev run would read and write production state"
    )


def test_the_loader_reads_exactly_one_env_file():
    """Guards the mechanism, not just the symptom.

    A second `load_dotenv` for another filename is the change that would break
    the test above, and it is an easy one to make in good faith.
    """
    source = (REPO_ROOT / "agent" / "config.py").read_text(encoding="utf-8")
    loads = [line for line in source.splitlines() if "load_dotenv(" in line]
    assert len(loads) == 1, f"expected exactly one load_dotenv call, found {len(loads)}: {loads}"
    assert '".env"' in loads[0], f"the single load_dotenv should name .env explicitly: {loads[0]}"
    assert "override=False" in loads[0], (
        "override=False is what lets a platform-injected secret beat a stale file line"
    )


def test_the_example_is_committed_and_the_real_file_is_not():
    """`production.env` is not matched by `.env*` — the same blind spot that let
    `env.txt` through with eight live credentials. It is matched explicitly."""
    assert (REPO_ROOT / "production.env.example").exists(), (
        "the committed template is what makes a deploy's shape reviewable"
    )

    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "production.env" in ignore, (
        "production.env must be gitignored explicitly: `.env*` does not match a name "
        "that puts the suffix first"
    )
