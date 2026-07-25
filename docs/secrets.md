# Secrets: what is exposed, what to rotate, and in what order

**Status: eight credentials are in this repository's git history and must be treated as public.**
They were committed in `408072f` and remain fetchable. Rotation is the only remediation. This
document is the record of what happened, the order to fix it in, and the check that stops the next
one.

> **Do not flip the repository public until the rotation below is done.** Going public is what
> turns a private exposure into a published one — a private repo limits who can fetch the blob to
> people who already have access.

---

## 1. What happened

`env.txt` — a verbatim copy of `.env` — was committed in **`408072f`** by a `git add -A`.
`.gitignore` covered `.env` but not `env.txt`, so nothing caught it. It was untracked and
gitignored in `899ae81`, and `.gitignore` now also matches `*env.txt`, `env*.txt`, `*.env.local`
and `secrets.*` — because the next one will be called something else.

**Untracking does not undo the exposure.** The blob was pushed, so it stays reachable on GitHub by
its SHA until GitHub garbage-collects, which needs a support ticket rather than a force-push. Every
clone and every reflog still holds it.

**A history purge was considered and deliberately declined.** It cannot close the hole — the blob
survives by SHA regardless — so it would buy hygiene against casual discovery at the cost of
breaking four active clones. One was attempted anyway, against that recorded decision, and had to
be undone (active-work #53, #55). **Rotation, not rewriting, is the remediation.** Once the
credentials are dead strings, the copies in history are worthless.

## 2. Rotation order

Ordered by what an attacker can do with each, not by convenience. Everything in §2.1 should be done
before the repository goes public.

### 2.1 Do these first

| # | Credential | Why it ranks here | How |
|---|---|---|---|
| **1** | **`UV_PUBLISH_TOKEN`** (PyPI) | 🔴 **The worst one, and not obviously so.** It can publish new versions of `curator-schema`, `curator-data` and `curator-mcp` — all three **live on PyPI**, and one of them (`curator-mcp`) is what The Graph's judges are invited to install with `uvx curator-mcp`. A malicious version would run on a judge's machine, and a PyPI version can never be recalled, only yanked. This is the only credential here that lets someone attack *other people* rather than us. | Revoke the token at pypi.org → Account settings → API tokens. Issue a new project-scoped token per package rather than an account-wide one. |
| **2** | `DEPLOYER_PRIVATE_KEY` | An EVM key. It holds no funds today, which is the only reason it is not first — a funded key would be. Anything ever sent to that address is sweepable by anyone reading the history. | Generate a new key. **Never send funds to the old address again.** |
| **3** | `X402_PRIVATE_KEY` | Same shape, and this one is *designed* to hold USDC for paid data queries. Fund the new key, not the old one. | As above. |

### 2.2 Then these

| Credential | Exposure |
|---|---|
| `GRAPH_API_KEY` | Billable gateway queries against our account. |
| `GRAPH_MARKET_API_KEY` / `TOKEN_API_KEY` | JWTs for the Token API. Rate limit and billing attach to us. |
| `ETHERSCAN_API_KEY` / `BASESCAN_API_KEY` | Rate limit only; free tier. Rotate for tidiness. |
| `uniswap_key` | Was only ever in `env.txt` (lowercased), which is why the live Uniswap path was unconfigured for a while. Rotate it and put it in `.env` as `UNISWAP_API_KEY`. |

### 2.2b A different kind of exposure — `XAI_API_KEY`

**This one is not in the repository, and filing it beside the others would misrepresent both.**
Verified rather than assumed, on 2026-07-26:

| Check | Result |
|---|---|
| In any commit, any branch (searched by **value**) | **0 commits** |
| In any tracked file | **none** |
| `.env` ignored | yes — `.gitignore:2` |
| In a local Claude Code transcript | **1 file** — `~/.claude/projects/…/6deb5778-….jsonl` (15.6 MB) |

So the Wave 3 plan's note that it *"was pasted into a chat transcript"* is correct, and that is the
whole of the exposure. What it means concretely:

- it sits in **plaintext in a user profile**, so anything that reads or syncs that directory — a
  backup, OneDrive, a shared machine — carries it;
- transcript content is **sent to Anthropic as conversation context**, so it has been transmitted to
  a third party;
- anything that ever attaches a transcript — a bug report, a support upload — would carry it further.

**Why it ranks below §2.1 rather than in it.** Everything in §2.1 is in **pushed git history**, so
flipping the repository public *publishes* it, and a pushed blob stays fetchable by its SHA
afterwards. That is why §2.1 gates the repo going public. This one does not: it is not in the
history, so going public discloses nothing new, and there is no history-rewrite question to weigh.

**Rotate it anyway** — it is live and billable, and rotation is one click in the xAI console followed
by editing `.env`. It simply does not need to block anything. Ordering it as though it did would push
the PyPI token down a list, and that is the one credential here that lets someone attack *other
people*.

> **The general lesson, which outlives this key:** a credential can leak without ever touching git.
> `scripts/check-secrets.sh` scans the repository and would never have seen this, and it is not a
> gap in the checker — it is the boundary of what a repository checker can be. Paste a key into a
> chat, a terminal that logs, or an issue tracker, and the only control left is rotation.

### 2.3 Not a secret, deliberately

**`AGENT_PRIVATE_KEY` is anvil account #1 and its key is printed in Foundry's own documentation.**
It is public by design and needs no rotation. The secrets checker allowlists all ten anvil keys for
the same reason: a checker that shouts about published test keys teaches everyone to bypass it, and
being loud about the public ones is how you end up quiet about the real ones.

## 3. The check that stops the next one

```bash
./scripts/check-secrets.sh                 # staged content — the pre-commit / pre-push use
./scripts/check-secrets.sh --install       # install as pre-commit AND pre-push hooks
./scripts/check-secrets.sh --tree          # every tracked file
./scripts/check-secrets.sh --history       # every commit ever
./scripts/check-secrets.sh --list-rules    # what it looks for, and why each rule exists
```

It combines **shape rules** (PyPI tokens, EVM private keys, GitHub/AWS/Slack/Google/OpenAI keys,
JWTs, RPC URLs with embedded keys, `KEY=`-style assignments) with an **entropy rule** for the
credential shapes nobody has enumerated yet.

**Calibrated against our own leak, in both directions:**

| Scan | Result |
|---|---|
| `--history 408072f~1..408072f` | **10 findings, all real, all in `env.txt`** — both private keys, the PyPI token, the JWT, four `API_KEY=` assignments. Zero false positives. |
| `--tree` (current repo) | **clean**, with 9 allowlisted values reported rather than hidden. |

The entropy threshold is **4.5 bits/character, measured rather than chosen.** Across this
repository the two populations do not overlap: `percentageFee` 2.81,
`testTheVaultRevertsWhenTheFeedIsStale` 3.71, `2026-07-25-master-build-plan` 4.01,
`invariantTotalAssetsEqualsSumOfHoldings` 4.19 — then nothing until a genuinely random string, a
Graph subgraph ID at 4.82. Base64 credentials sit near 5.5. A first pass at 3.6 reported 554
findings, every one of them a file path or an identifier in a markdown document; a checker at that
signal-to-noise ratio is one that gets switched off, which is worse than not having it.

**Compiled artifacts and lockfiles are skipped** (`contracts/out`, `contracts/abis`,
`program_builder.json`, `pnpm-lock.yaml`, `uv.lock`, `node_modules`). A committed bytecode blob is
tens of kilobytes of maximum-entropy hex that can never be a credential.

**Two escape hatches, both deliberately visible.** End a line with `secrets-check: allow` to
suppress it in place, or add a pattern to [`.secrets-allow`](../.secrets-allow) for a value that is
high-entropy *and* public. Allowlisted hits are **counted and reported**, never silently dropped —
a suppression nobody can see is the same failure mode as a rule that does not exist. And the one
rule that keeps that file honest: **only public identifiers go in it.** Pasting a credential there
to quiet the checker commits the credential, by hand, into a tracked file.

## 4. The habits that actually matter

1. **Stage explicit paths. Never `git add -A`, never `git commit -a`.** That single command caused
   this leak and swept three lanes' work into the wrong commits twice in each direction (#14, #21).
2. **Real values go in `.env`**, which is gitignored. `.env.example` carries names and placeholders
   only. Never create a second copy under a new name to "keep a backup".
3. **A hook is local and unversioned.** `--install` protects your clone; it does not protect a
   teammate's. Run `--tree` before anything that makes the repository more public.
4. **If it leaks anyway: rotate first, and say so in `docs/active-work.md` immediately.** Do not
   reach for `filter-branch`. It breaks every clone, races in-flight pushes, and closes nothing —
   we have the receipt.
