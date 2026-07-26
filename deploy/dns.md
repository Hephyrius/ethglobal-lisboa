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
record you add will take effect while it is there. Namecheap implements it as an
address record under the hood, so depending on how the domain was set up the apex
entry may show in the UI as **URL Redirect Record** *or* as a plain **A Record**
pointing at a `192.64.119.x` parking address. Delete whichever one is there —
queried authoritatively on 2026-07-26, this zone has it as `A @ 192.64.119.212`.

### Do not delete the other six — they are email forwarding

"Delete the defaults" is too broad a rule, and the records it would take out with
it do not announce what they are for. This zone also carries:

| Type | Host | Value | |
|---|---|---|---|
| MX Record | `@` | `eforward1.registrar-servers.com` (priority 10) | **keep** |
| MX Record | `@` | `eforward2.registrar-servers.com` (10) | **keep** |
| MX Record | `@` | `eforward3.registrar-servers.com` (10) | **keep** |
| MX Record | `@` | `eforward4.registrar-servers.com` (15) | **keep** |
| MX Record | `@` | `eforward5.registrar-servers.com` (20) | **keep** |
| TXT Record | `@` | `v=spf1 include:spf.efwd.registrar-servers.com ~all` | **keep** |

These are Namecheap's free email forwarding and its SPF record. They share the
apex with the A record but never conflict with it — MX and TXT answer different
query types than A, so hosting the site on Vercel and forwarding mail through
Namecheap coexist with no interaction at all. Removing them silently stops
delivery to any `@scipio.capital` address, and mail failures are not visible from
the site being up. Leave them alone.

## 3. Add these

**Advanced DNS** → *Host Records* → *Add New Record*.

| Type | Host | Value | TTL |
|---|---|---|---|
| A Record | `@` | `76.76.21.21` | Automatic |
| CNAME Record | `www` | `cname.vercel-dns.com.` | Automatic |
| A Record | `api` | `138.68.159.44` | Automatic |
| AAAA Record | `api` | `2a03:b0c0:1:e0:0:1:99fe:2001` | Automatic |

Notes on each, because three of the four have a trap:

- **`@` → 76.76.21.21** is Vercel's *legacy* shared apex address, and newer
  projects are issued `216.198.79.1` instead. ⚠️ **Confirm it against
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

**✅ Section 3 is applied and globally propagated (verified 2026-07-26).** All
three names agree on Google, Cloudflare and Quad9, and the email-forwarding
records survived the edit:

| Name | Resolves to | |
|---|---|---|
| `scipio.capital` | `76.76.21.21` | Vercel |
| `www.scipio.capital` | `cname.vercel-dns.com.` → Vercel edge | Vercel |
| `api.scipio.capital` | `138.68.159.44` + the AAAA | the droplet |
| `@` MX ×5 / SPF TXT | `eforward*.registrar-servers.com` | intact |

⚠️ **A resolver that still shows `192.64.119.212` is caching, not broken.** The
old parking record and the old `api.` NXDOMAIN both persist in local and ISP
caches after the authoritative zone is correct — negative caching is the reason
`api.` in particular can stay dead on one machine long after it works
everywhere. `Clear-DnsClientCache` (Windows) or `resolvectl flush-caches`
(Linux) fixes the local half; the ISP's is a matter of waiting out the TTL.
Query `8.8.8.8` directly to see the truth, or use `curl --resolve` to bypass
resolution entirely — it sets SNI as well as the address, which
`--header 'Host: …'` does not, and a wrong SNI is indistinguishable from a
missing certificate.

### DNS resolving is not the same as TLS working

Both halves of this deployment were still failing their handshake immediately
after propagation, for two unrelated reasons worth telling apart:

**`api.` — Caddy holds no certificate.** Port 80 is healthy and proves the
config is loaded: `curl --resolve api.scipio.capital:80:138.68.159.44` returns
Caddy's own `308` to HTTPS for that exact hostname, so the site block is
matching. Port 443 answers `no peer certificate available` and a TLS internal
error. That is the signature of a Caddy that exhausted its ACME attempts while
the name was NXDOMAIN and has backed off — the backoff is exponential and can
run for hours, so it does **not** heal itself on a useful timescale once DNS
lands. Restart the container to force an immediate retry:

```sh
uv run --with paramiko python scripts/vps.py deploy   # or: docker compose restart caddy
curl -s https://api.scipio.capital/health
```

**The apex — the domain is not attached to a Vercel project.** `76.76.21.21`
accepts TCP and serves a valid `*.vercel.com` certificate for a name it knows,
and refuses the handshake for `scipio.capital`. Vercel terminates TLS only for
hostnames configured on a project, so this is not a DNS fault and no amount of
waiting changes it. Pointing the record at Vercel is one half; adding the domain
under Project → Settings → Domains is the other, and §5 below is what makes the
resulting build correct.

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
| `NEXT_PUBLIC_RPC_URL` | the same archive-capable URL as `BASE_RPC_URL` |

⚠️ **`NEXT_PUBLIC_RPC_URL` is the row that gets forgotten, and it fails quietly.**
It is the browser's own read RPC — every `totalAssets()`, share balance and
wallet balance on the dashboard goes through it, not through the API. Left
unset, `src/lib/chain/wagmi.ts` calls `http(undefined)` and viem falls back to
Base's public endpoint, which is `https://mainnet.base.org` — the exact endpoint
[README.md](README.md) tells you not to use, now serving every judge who opens
the page. Nothing errors; the vault panels just get slow and start dropping
reads under rate limiting.

Do **not** paste a localhost URL here. `src/lib/chain/explorer.ts` treats a
local hostname as proof it is on the anvil fork and suppresses every BaseScan
link on the site, because the fork also reports chain id 8453.

There is no `NEXT_PUBLIC_WALLETCONNECT_ID`. The connector is injected-only and
nothing reads that variable — see the rationale at the top of
`src/lib/chain/wagmi.ts`. `NEXT_PUBLIC_SITE_URL` exists but already defaults to
`https://scipio.capital`, so it only needs setting on a preview deployment whose
link previews should point at itself.

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
