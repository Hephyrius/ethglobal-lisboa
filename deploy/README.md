# Deploying scipio.capital

Real Base mainnet. The dApp is on Vercel; the API is on a DigitalOcean droplet
behind Caddy. Everything here is ordered so each step is verifiable before the
next one costs money.

```
scipio.capital       ──► Vercel                     (Next.js, built by Vercel)
api.scipio.capital   ──► Caddy ──► api :8000        (FastAPI + the agent loop)
                                     └─► Base mainnet via BASE_RPC_URL
```

**DNS records: [dns.md](dns.md).** Do that first — Caddy asks Let's Encrypt for
a certificate the moment it starts, and failed challenges are rate-limited.

There is **no anvil service.** The chain is real. There is also **no CI**:
`scripts/vps.py deploy` uploads the tree and builds on the box. The dApp is the
only thing that could not be built there, and Vercel builds that.

---

## 0. Before anything costs gas

The contracts are irreversible in one specific way and it is worth stating once:
**`AGENT_ROLE` cannot be revoked.** `Deploy.s.sol` refuses to run on a real
network with an anvil key (`UnsafeAnvilKeyOnRealNetwork`) because those keys are
in Foundry's published docs, and a vault whose agent key is public could only be
abandoned, never repaired.

Two accounts need real ETH on Base **before** the deploy:

| Account | Needs | Why |
|---|---|---|
| `DEPLOYER_PRIVATE_KEY` | ~0.003 ETH | one factory + one vault |
| `AGENT_PRIVATE_KEY` | ~0.005 ETH | every tick is a transaction, forever |

An unfunded agent is the failure this repo has already had: the whole stack
reports healthy, the model reasons correctly, all six validation layers pass,
and only the final broadcast fails with `-32003`. `scripts/preflight.sh` now
checks it.

⚠️ **`.env` currently carries the anvil agent key**, which is correct for the
fork and wrong here. It is commented directly above the active line. One `.env`
serves both, so this is the line you change — see `.env.example`.

### Check the oracle before you deploy, not after

On `base-fork`, `priceMaxAge` is 0 and staleness checking is off. On any real
network it is **3600 seconds**, and `totalAssets()` *reverts* if a feed for a
token the vault holds is older than that. A reverting `totalAssets()` means
nobody can deposit and nobody can withdraw.

`Deploy.s.sol` already probes every configured feed at the exact `priceMaxAge`
it is about to freeze, so a stale feed fails the deploy rather than producing a
bricked vault. Verified 2026-07-26 against live Base: the ETH/USD feed
(`0x71041ddd…`) had updated 820s earlier against its 1200s heartbeat. Healthy,
with room.

---

## 1. Contracts → Base mainnet

From `contracts/`, in `wsl -d Ubuntu-24.04` (or natively on macOS):

```sh
DEPLOY_NETWORK=base-mainnet forge script script/Deploy.s.sol \
  --rpc-url "$BASE_RPC_URL" --broadcast --slow
```

Writes `deployments/base-mainnet.json`. **Commit that file** — every other
component reads addresses from it, and the web bundle compiles it in.

> A placeholder `deployments/base-mainnet.json` full of nulls is already
> committed. It exists because `web/src/lib/chain/deployments.ts` imports it
> *statically*, and a TypeScript build cannot import a file that is not there.
> The deploy overwrites it.

Then the two post-deploy checks, which ask different questions:

```sh
NETWORK=base-mainnet ./script/check-deployment.sh   # is the bytecode this source?
DEPLOY_NETWORK=base-mainnet forge script script/VerifyDeployment.s.sol \
  --rpc-url "$BASE_RPC_URL"                          # is the live state what the file claims?
./script/verify.sh base-mainnet                      # publish source to the explorer
```

A vault passes the first and fails the second in every way that matters: right
code and the wrong agent, right code and an allowlist missing the router every
plan targets.

---

## 2. DNS

Full Namecheap walkthrough, including the two default records that must be
deleted first: **[dns.md](dns.md)**.

The shape: the apex and `www` point at **Vercel**, and only `api.` points at the
droplet. Getting that backwards sends API calls to Vercel, which answers 404,
and the dApp then reports the agent as unreachable.

Confirm before starting Caddy — it requests a certificate on first boot, and
failed ACME challenges are rate-limited to five per hostname per hour:

```sh
dig +short api.scipio.capital     # → the droplet's IPv4
```

---

## 3. The box

The droplet is **1 vCPU, 961 MiB RAM, 24 GB disk, and shipped with no swap**.
That is the governing fact of this section.

`next build` peaks well above a gigabyte, which is why the dApp is on Vercel
rather than here. What remains is a Python image with no compiler in it, and
that builds on the box in a couple of minutes — so there is no registry and no
CI in the loop. Measured after a real deploy: **508 MiB of 961 in use, 18 MiB of
swap touched.**

There is no git checkout on the droplet either. It holds `docker-compose.yml`,
`Caddyfile`, `update.sh`, `.env` and an unpacked `src/` tree that `deploy`
replaces wholesale each time — so nothing there can drift, and a file deleted
locally cannot linger and get compiled into the next image.

Everything is driven from a dev machine by one script:

```sh
uv run --with paramiko python scripts/vps.py provision   # idempotent
uv run --with paramiko python scripts/vps.py keys        # then retire the password
uv run --with paramiko python scripts/vps.py push-env    # .env, over SFTP, 0600
uv run --with paramiko python scripts/vps.py deploy      # sync + build + restart + verify
uv run --with paramiko python scripts/vps.py info        # what is it doing
uv run --with paramiko python scripts/vps.py logs
```

`provision` installs Docker, adds a **4 GB swapfile** (the box ships with none,
so the kernel's only answer to a memory spike is the OOM killer, and it would
pick the agent loop mid-tick), sets `vm.swappiness=20`, caps Docker and journald
logs, and enables ufw + fail2ban. It is safe to re-run.

### The .env lines that must change from a laptop

| Variable | Laptop | Here |
|---|---|---|
| `AGENT_PRIVATE_KEY` | anvil #1 | a real funded key |
| `DEPLOYER_PRIVATE_KEY` | anvil #0 | a real funded key |
| `DEPLOY_NETWORK` | unset (`base-fork`) | `base-mainnet` |
| `BASE_RPC_URL` | any | archive-capable, **not** `mainnet.base.org` |
| `XAI_API_KEY` | optional | **set it** — without it the backend falls back to Ollama and tries to reach `localhost:11434`, which in a container is nothing at all |

`docker-compose.yml` overrides `AGENT_MODE`, `DEPLOY_NETWORK`, `ANVIL_RPC_URL`,
`AGENT_STATE_DIR` and the CORS origins in `environment:`. That is not
belt-and-braces: `agent/config.py` loads `.env` with `override=False`, so a real
environment variable always beats a file line, and each of those fails silently
in its own way if a dev value reaches production.

⚠️ **The CORS origins are read from `PROD_CORS_ORIGINS`, not
`AGENT_CORS_ORIGINS`, and that is deliberate.** Compose interpolates
`${VAR:-default}` against the `.env` beside it — the laptop's — which sets
`AGENT_CORS_ORIGINS` to localhost and WSL bridge addresses. The `:-` default
would never fire and the deployed API would inherit a dev CORS policy permitting
nothing the real site is served from. That happened on the first deploy and
`update.sh` caught it with a 400 on the preflight. A name the dev `.env` never
sets is the fix.

`ANVIL_RPC_URL` is overridden to `BASE_RPC_URL` deliberately. Despite the name,
most of the harness reads it as *"the chain to talk to"*; left at `:8540` while
`BASE_RPC_URL` is real, the agent reads one chain and writes another.

---

## 4. Verify, in this order

```sh
curl -s https://api.scipio.capital/health          # mode: live, all three seams
curl -s https://api.scipio.capital/venues          # four venues, not a 503
curl -s -X OPTIONS https://api.scipio.capital/health \
     -H "Origin: https://scipio.capital" \
     -H "Access-Control-Request-Method: GET" -o /dev/null -w '%{http_code}\n'   # 200, not 400
curl -s -o /dev/null -w '%{http_code}\n' https://scipio.capital
```

**`mode: live` is the one that matters.** A fixture-mode API answers every
request and validates every response over invented data, so a stack left in
fixture mode looks completely healthy from the outside. The container's own
healthcheck asserts `mode == "live"` for the same reason.

The CORS preflight is worth its own line because its failure mode is misleading:
a rejected origin gets a 400, the dApp falls back to reading the chain, and it
reports *"the agent API is unreachable"* — which reads as a dead backend when
the backend is fine.

---

## 5. Updating

```sh
uv run --with paramiko python scripts/vps.py deploy
```

That is the whole loop. It uploads the current **working tree** (not `HEAD` — a
deploy that silently shipped the last commit instead of what you are looking at
would be the worst kind of wrong), rebuilds the API image on the box, restarts,
and then verifies rather than assuming:

- `docker compose up -d` returns when containers are *created*. A crashloop
  satisfies it. So the script polls until the API answers.
- It checks `"mode":"live"` specifically, because a fixture-mode API answers
  every request and validates every response over invented data.
- It runs a **CORS preflight from `https://scipio.capital`**. That seam fails
  silently in the worst way: a rejected origin returns 400, the dApp falls back
  to reading the chain, and it reports *"the agent API is unreachable"* — which
  reads as a dead backend while everything else is green. This check caught
  exactly that on the first deploy.

Both probes run *inside* the container, because the API is `expose:`d rather
than published; it is reachable only through Caddy and the compose network. An
earlier version curled `localhost:8000` from the host, got connection-refused
against a perfectly healthy API, and called the deploy failed.

The dApp updates itself: Vercel builds on push.

The `agent-state` volume survives rebuilds and must. It holds mandates (only the
hash is on chain) and **every open Aqua position** — Aqua can confirm a strategy
hash you already hold but cannot enumerate a maker's positions, so a lost record
is a position that can never be displayed or closed. `update.sh` prunes images
and build cache, never volumes.

## What this deployment does *not* do

Stated so nobody discovers it during a demo.

- **No process ticks on a schedule.** `POST /vault/{addr}/tick` is called by the
  dApp or by hand. There is no cron, and adding one on real Base means real gas
  on every tick.
- **No backups of the state volume.** `docker run --rm -v scipio_agent-state:/s
  -v $PWD:/b alpine tar czf /b/state.tgz -C /s .` is the whole procedure; run it
  before any `docker compose down -v`.
- **`down -v` destroys the Aqua position records.** There is no recovery.
