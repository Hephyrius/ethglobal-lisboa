# Spending 0.0099 ETH on Base — what it buys, and how to split it

**Nothing has been sent. No transaction has been broadcast.** This is the plan
to sign off on first.

Funder: `0xD82C420F4C5B47C4Ec480DD0BA8f7d7CE7A69bD7`
Holds: **0.00990919 ETH ($18.62)** and **0 USDC**.

Priced 2026-07-26 at Base L2 **0.006 gwei** and ETH **$1,878.96** (the vault's own
Chainlink feed).

---

## What things cost

All gas below is **measured**, not estimated — from `forge test --gas-report`
over the fork test suite, from the deploy's own broadcast receipts, and from
`eth_estimateGas` against the live fork.

| Operation | Gas (median) | Range | Cost | Source |
|---|---:|---:|---:|---|
| Plain ETH transfer | 21,000 | — | $0.00024 | protocol |
| USDC `approve` | 55,819 | — | $0.00063 | `eth_estimateGas`, fork |
| Vault `deposit` | 318,753 | 223k – 355k | $0.0036 | gas report, fork tests |
| `executeBatch` — vault overhead only | 62,425 | 10k – 145k | $0.0007 | gas report |
| `redeem` | 226,781 | 80k – 366k | $0.0026 | gas report, fork tests |
| `redeemInKind` | 230,632 | 80k – 381k | $0.0026 | gas report, fork tests |
| `createVault` — one vault | 1,649,899 | — | $0.0186 | `eth_estimateGas`, fork |
| Full `Deploy.s.sol` | 5,881,769 | — | $0.0663 | broadcast receipts |

Two of those need reading carefully:

**`executeBatch` at 62k is the vault's overhead, not a tick.** It is the
allowlist check, the loop and the call dispatch — the venue's own work is
whatever the target costs. A real tick is that overhead plus an approval plus
the venue call: an Aave supply is roughly 250k, a Uniswap rotation through the
Universal Router 200–300k. **Budget ~450,000 gas per tick, ≈ $0.0051.** That is
the one number below built from a component sum rather than measured end to end.

**`createVault` is configuration-dependent.** The unit tests report a 752k
median, but the live fork estimates 1,649,899 — the difference is the eight
token valuations the factory now carries, each costing storage. The larger
figure is the one for the current configuration, so it is the one used here.

### The L1 data fee is not a factor, and that is worth stating

On an L2 the L1 blob-posting fee is usually the dominant cost of a small
transaction, and `eth_gasPrice` does not include it. Checked against Base's own
`GasPriceOracle` and cross-checked against real receipts in the latest block:
**~$0.000001 per transaction.** At current blob prices it rounds to nothing.
That is a fact about today, not a property of Base — it is worth re-checking if
Ethereum blob demand spikes.

## The whole campaign, at today's prices

15 vaults, each deposited into, each ticking three times:

| | Count | Cost |
|---|---:|---:|
| `Deploy.s.sol` (once) | 1 | $0.066 |
| `createVault` | 15 | $0.279 |
| approve + deposit | 15 | $0.063 |
| agent ticks @ 450k | 45 | $0.230 |
| **Total gas** | | **≈ $0.64** |

Exiting afterwards, if you want the capital back, adds 15 × `redeem` = $0.04.

**$0.65 of an $18.62 budget.** Gas is not the constraint. Two other things are.

---

## Constraint 1 — gas price is the risk, not gas usage

$0.65 assumes 0.006 gwei, which is a quiet Base. Base's base fee moves over two
orders of magnitude with activity, and a demo happens when other people are also
demoing.

| If gas is | Campaign costs |
|---|---:|
| 0.006 gwei (now) | $0.65 |
| 0.06 gwei (10×) | $6.50 |
| 0.3 gwei (50×) | $32.50 — **over budget** |

So the allocation below is sized for roughly a **10–15× spike**, not for today.
Sizing to today's price would look generous and leave the agent unable to
transact during exactly the hour that matters.

## Constraint 2 — there is no USDC, and the vaults are USDC-denominated

The funder holds **zero USDC**. Every mandate's `base_asset` is USDC, so vault
capital cannot come from the ETH balance directly — some has to be swapped.

At $0.50 × 15 deployments that is **$7.50**, which is 40% of the total budget
and by far the largest line item. Gas is a rounding error next to it.

### ⚠️ $0.10–$0.50 per vault is below the size the demo path actually works at

This is the one place I would push back on the number before you sign it off.

- **A Uniswap rotation of $0.50 is unlikely to price sensibly.** The Trading API
  may return no route, and if it does, the gas to execute the swap ($0.006 now,
  $0.06 in a spike) is a meaningful fraction of the trade — which shows up as
  realised slippage against a mandate ceiling of 50 bps and gets the plan
  rejected by validation layer 4. The rejection would be *correct*, and it would
  look like the agent refusing to trade.
- **An Aave supply of $0.50 earns nothing observable.** The APY panel would read
  a real rate against a position too small to produce a visible return, and the
  performance history needs 24h to annualise anyway.
- **Share-price precision is fine** — `_decimalsOffset() = 12` handles it — so
  this is an economics problem, not an accounting one.

**Recommendation: fewer, larger vaults.** Four vaults at $1.50 costs the same
$6.00 and every one of them can actually rotate, supply and show a number. If
you want fifteen vaults *visible*, deploy fifteen and fund four — an unfunded
vault still proves genesis, the mandate hash and the factory, which is most of
what a judge clicks.

---

## Proposed split of 0.00990919 ETH

| Destination | ETH | USD | Why this much |
|---|---:|---:|---|
| **Swap → USDC** (vault capital) | 0.00400 | $7.52 | 15 × $0.50, or 4 × $1.50 with room. The largest line and the one that is actually scarce. |
| **Deployer** `0x92D4…611b` | 0.00150 | $2.82 | Factory + 15 `createVault` = $0.35 today. This is ~8× headroom, and it must clear the script's own floor. |
| **Agent** `0x75E5…2b5c` | 0.00250 | $4.70 | Every tick forever. ~$0.25 for 45 ticks today, so ~19× headroom. The account that must never run dry mid-demo. |
| **Funder retains** | 0.00191 | $3.58 | Swap gas, three transfers, and a top-up reserve. |
| | **0.00991** | **$18.62** | |

### Two hard facts behind those numbers

**The deployer floor is enforced by the contract, not by judgement.**
`Deploy.s.sol` reverts with `DeployerCannotPayGas(deployer, 0, 1e15)` below
**0.001 ETH**. I hit this running the dry run. 0.0015 clears it with margin.

**The agent gets the most because it is the one that cannot be topped up
mid-demo without someone noticing.** An unfunded agent is a failure this repo
has already had: `/health` green on all three seams, the model reasoning
correctly, all six validation layers passing, and only the broadcast failing
with `-32003`. `scripts/preflight.sh` now gates on it, but the gate tells you
after the fact.

### Order of operations, when you sign off

1. Swap **0.0040 ETH → USDC** on the funder. Do this first — it is the only step
   with market risk, and if the route is bad you will want to know before the
   ETH is split three ways.
2. Send **0.0015 ETH** to the deployer.
3. Send **0.0025 ETH** to the agent.
4. `scripts/preflight.sh` against mainnet — it checks the agent key matches the
   vault's agent and holds gas.
5. Only then `DEPLOY_NETWORK=base-mainnet forge script Deploy.s.sol --broadcast`.

Nothing above step 5 touches the contracts, so 1–4 are reversible in the sense
that the funds stay in wallets you control.

### What I have not done

No transaction has been signed or sent. No swap route has been quoted. The
`AGENT_PRIVATE_KEY` in `.env` is still anvil #1 — correct for the fork, and it
**must** be switched to the mainnet key before step 3, or the ETH goes to an
account with no `AGENT_ROLE`.
