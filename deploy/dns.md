# DNS for scipio.capital (Namecheap)

Two destinations, because the dApp and the API are hosted in different places:

```
scipio.capital        →  Vercel     (Next.js, built and served by Vercel)
www.scipio.capital    →  Vercel
api.scipio.capital    →  138.68.159.44   (the droplet: FastAPI behind Caddy)
```

---

## 1. Make sure Namecheap is actually serving DNS

Namecheap → **Domain List** → *Manage* → **Nameservers**.

It must say **Namecheap BasicDNS**. If it says Custom DNS or anything else, the
**Advanced DNS** tab's records are ignored entirely — they are still displayed,
still editable, and have no effect. That is the single most common reason a
Namecheap domain "doesn't propagate".

## 2. Delete what Namecheap ships by default

Same page, **Advanced DNS** tab. A new domain arrives with two records that will
actively fight this setup:

| Type | Host | Value | |
|---|---|---|---|
| CNAME Record | `www` | `parkingpage.namecheap.com.` | **delete** |
| URL Redirect Record | `@` | `http://www.scipio.capital/` | **delete** |

The URL Redirect is the nastier one: it makes the apex answer with a redirect
rather than an address, so the site appears to load and then bounces, and no A
record you add will take effect while it is there.

## 3. Add these

**Advanced DNS** → *Host Records* → *Add New Record*.

| Type | Host | Value | TTL |
|---|---|---|---|
| A Record | `@` | `76.76.21.21` | Automatic |
| CNAME Record | `www` | `cname.vercel-dns.com.` | Automatic |
| A Record | `api` | `138.68.159.44` | Automatic |
| AAAA Record | `api` | `2a03:b0c0:1:e0:0:1:99fe:2001` | Automatic |

Notes on each, because three of the four have a trap:

- **`@` → 76.76.21.21** is Vercel's shared apex address. ⚠️ **Confirm it against
  your own Vercel dashboard** (Project → Settings → Domains → add
  `scipio.capital`). Vercel shows the exact record for *your* project there and
  occasionally issues a different one; the dashboard is authoritative and this
  table is not.
- **`www` → CNAME** rather than an A record, because Vercel's `www` target is a
  load-balanced name whose addresses change. Namecheap adds the trailing dot for
  you if you leave it off.
- **`api` A record points at the droplet, not Vercel.** This is the split that
  makes the whole thing work; getting it backwards sends API calls to Vercel,
  which answers 404, and the dApp reports the agent as unreachable.
- **AAAA is optional but worth having** — the droplet has a public IPv6 and some
  mobile networks are v6-only. Skip it only if it complicates things; nothing
  depends on it.

You do **not** need a CAA record. Add one only if you already have CAA entries,
in which case both issuers need permission:

```
CAA  @  0 issue "letsencrypt.org"     ← Caddy, for api.
CAA  @  0 issue "sectigo.com"          ← Vercel
```

## 4. Wait, then verify — before starting Caddy

```sh
dig +short scipio.capital        # → 76.76.21.21
dig +short www.scipio.capital    # → cname.vercel-dns.com. then an IP
dig +short api.scipio.capital    # → 138.68.159.44
```

Namecheap is usually live within a few minutes but says up to 30. **Do not start
Caddy before `api.scipio.capital` resolves.** Caddy requests a certificate on
first boot, and a failed ACME challenge counts against Let's Encrypt's limit of
**five failures per hostname per hour** — long enough to keep the API offline
through a demo. It retries with backoff, so an early start is recoverable, just
slow at exactly the wrong moment.

Once resolution is confirmed:

```sh
uv run --with paramiko python scripts/vps.py deploy
curl -s https://api.scipio.capital/health
```

The first HTTPS request may take a few seconds while Caddy completes the ACME
handshake. After that the certificate is in the `caddy-data` volume and renews
itself.

## 5. Vercel side

Project → Settings → Environment Variables. These are **inlined into the
JavaScript bundle at build time**, so changing one requires a redeploy — setting
it and restarting does nothing.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.scipio.capital` |
| `NEXT_PUBLIC_CHAIN_ID` | `8453` |
| `NEXT_PUBLIC_DEPLOY_NETWORK` | `base-mainnet` |
| `NEXT_PUBLIC_WALLETCONNECT_ID` | *(only if the WalletConnect connector is used)* |

Build settings for this repo, which is a pnpm workspace:

- **Root Directory:** `web`
- **Include source files outside of the Root Directory:** **on**. Required, not
  optional — `web/src/lib/chain/deployments.ts` imports
  `../../../../deployments/*.json` and `lib/api/fixtures.ts` imports
  `../../../../packages/schema/fixtures/*.json`. Without this the build fails on
  module resolution.
- Framework preset Next.js; install and build commands can stay on the defaults,
  which detect pnpm from `pnpm-lock.yaml`.

### One thing that will bite: CORS on preview deployments

Every branch and every commit gets its own Vercel hostname. That origin is not
`https://scipio.capital`, so the API refuses its preflight with a 400 and the
dApp reports *"the agent API is unreachable"* — which reads as a dead backend
while the backend is perfectly healthy.

That is the correct default: an allowlist accepting `*.vercel.app` would accept
anybody's Vercel project. To let a specific preview talk to the live API, add
its exact hostname to `AGENT_CORS_ORIGINS` in `.env` and re-run
`scripts/vps.py push-env && scripts/vps.py deploy`.
