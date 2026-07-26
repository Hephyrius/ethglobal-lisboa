# Deploying scipio.capital

Real Base mainnet, one VPS, Caddy for TLS. Everything here is ordered so that
each step is verifiable before the next one costs money.

```
scipio.capital       ──► Caddy ──► web  :3000   (Next.js)
api.scipio.capital   ──► Caddy ──► api  :8000   (FastAPI + the agent loop)
                                      └─► Base mainnet via BASE_RPC_URL
```

There is **no anvil service.** The chain is real.

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

## 2. DNS — do this before the first `compose up`

Two A records at your registrar, both to the VPS's IPv4:

```
scipio.capital        A   <VPS IP>
api.scipio.capital    A   <VPS IP>
www.scipio.capital    A   <VPS IP>     (optional; the Caddyfile serves it)
```

Caddy issues certificates over ACME on first start. If DNS is not resolving yet
it retries, but each failure counts against Let's Encrypt's limit of **five per
hostname per hour** — enough to keep the site down for the length of a demo.
Confirm resolution first:

```sh
dig +short scipio.capital api.scipio.capital
```

---

## 3. The box

Docker Engine and the compose plugin. Then, from the repo root:

```sh
git clone https://github.com/Hephyrius/ethglobal-lisboa && cd ethglobal-lisboa
cp .env.example .env      # then fill it in — see the checklist below
docker compose -f deploy/docker-compose.yml up -d --build
```

### The .env lines that must change from a laptop

| Variable | Laptop | Here |
|---|---|---|
| `AGENT_PRIVATE_KEY` | anvil #1 | a real funded key |
| `DEPLOYER_PRIVATE_KEY` | anvil #0 | a real funded key |
| `DEPLOY_NETWORK` | unset (`base-fork`) | `base-mainnet` |
| `BASE_RPC_URL` | any | archive-capable, **not** `mainnet.base.org` |
| `XAI_API_KEY` | optional | **set it** — without it the backend falls back to Ollama and tries to reach `localhost:11434`, which in a container is nothing at all |

`docker-compose.yml` overrides `AGENT_MODE`, `DEPLOY_NETWORK`, `ANVIL_RPC_URL`,
`AGENT_STATE_DIR` and `AGENT_CORS_ORIGINS` in `environment:`. That is not
belt-and-braces: `agent/config.py` loads `.env` with `override=False`, so a real
environment variable always beats a file line, and each of those five fails
silently in its own way if a dev value reaches production.

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

## 5. Rebuilding

```sh
git pull
docker compose -f deploy/docker-compose.yml up -d --build
```

⚠️ **`--build` is not optional for the web container.** `NEXT_PUBLIC_*` are
inlined into the JavaScript bundle by `next build`. Without `--build`, compose
reuses the existing image and the old values stay compiled in — the symptom is a
deployed site quietly talking to `http://localhost:8000`, which fails only in a
visitor's browser and appears in none of your logs.

The `agent-state` volume survives rebuilds and must. It holds mandates (a
mandate cannot be recovered; only its hash is on chain) and **every open Aqua
position** — Aqua can confirm a strategy hash you already hold but offers no way
to enumerate a maker's positions, so a lost record is a position that can never
be displayed or closed.

---

## What this deployment does *not* do

Stated so nobody discovers it during a demo.

- **No process ticks on a schedule.** `POST /vault/{addr}/tick` is called by the
  dApp or by hand. There is no cron, and adding one on real Base means real gas
  on every tick.
- **No backups of the state volume.** `docker run --rm -v scipio_agent-state:/s
  -v $PWD:/b alpine tar czf /b/state.tgz -C /s .` is the whole procedure; run it
  before any `docker compose down -v`.
- **`down -v` destroys the Aqua position records.** There is no recovery.
