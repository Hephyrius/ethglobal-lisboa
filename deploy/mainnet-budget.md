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

At **1 USDC × 10–15 vaults** that is **$10–15**, which is most of the budget and
by far the largest line item. Gas is a rounding error next to it.

### Correction: 1 USDC per vault works. My earlier warning here was wrong.

An earlier version of this file said a sub-dollar rotation might not route, and
that gas would eat enough of the trade to breach the mandate's 50 bps ceiling
and be rejected by validation layer 4. **Both claims were wrong, and they were
wrong in the direction that would have cost money** — they argued for larger
deposits than the demo needs.

Measured against the live Trading API rather than reasoned about:

| Trade | WETH out | Implied $/ETH | Gas |
|---:|---:|---:|---:|
| 0.25 USDC | 0.000132809 | $1,882.40 | $0.0011 |
| 1 USDC | 0.000531235 | $1,882.41 | $0.0011 |
| 5 USDC | 0.002656165 | $1,882.41 | $0.0011 |
| 500 USDC | 0.265500947 | $1,883.23 | $0.0025 |

Every size routes. The **small trade gets the better price** — 4 bps better than
the 500 USDC one, because it moves the pool less. Slippage tolerance is a
percentage, so it does not tighten as size falls; that was the error in the
original reasoning.

The full cycle was then re-run end to end at exactly 1 USDC. Aave supply and
withdraw, Morpho supply and withdraw, the atomic multi-intent batch, pause with
redemption open, `redeemInKind`, and the closing accounting invariant **all pass
at 1 USDC**. Nothing rounds to zero: 1 USDC is 1,000,000 base units, and
`_decimalsOffset() = 12` keeps share pricing exact.

**What is true at this size is an economics point, not an execution one.** Gas
of $0.0011 a swap against a 1 USDC position earning ~3.5% is more than a year of
yield in one transaction. That is entirely fine for a demonstration — the point
is that the agent reasons, decides and executes, not that it turns a profit on a
dollar — but do not let the performance panel be read as a return.

One thing genuinely does change below ~100 USDC: `data/curator_data/sources/peers.py`
sets `MIN_PEER_ASSETS = 100.0`, so a 1 USDC vault is invisible to the peer
comparison. It will not appear as a peer to other vaults and will not see itself
ranked. Deliberate — a fork accumulates dozens of unfunded vaults and they say
nothing about strategy — but worth knowing before someone asks why the peer
panel is empty.

## Proposed split of 0.00990919 ETH

| Destination | ETH | USD | Why this much |
|---|---:|---:|---|
| **Swap → USDC** (vault capital) | 0.00560 | $10.52 | 10 vaults × 1 USDC with room to spare, or 15 at a squeeze. The largest line and the only genuinely scarce one. |
| **Deployer** `0x92D4…611b` | 0.00120 | $2.26 | Factory + 15 `createVault` = $0.35 today, so ~6× headroom, and it clears the script's own 0.001 ETH floor. |
| **Agent** `0x75E5…2b5c` | 0.00200 | $3.76 | Every tick forever. ~$0.25 for 45 ticks today, so ~15× headroom. The account that must never run dry mid-demo. |
| **Funder retains** | 0.00111 | $2.08 | Swap gas, the transfers, the deposit approvals, and a top-up reserve. The funder is also the demo depositor, so the USDC stays here and moves into vaults at deposit time. |
| | **0.00991** | **$18.62** | |

### Two hard facts behind those numbers

**The deployer floor is enforced by the contract, not by judgement.**
`Deploy.s.sol` reverts with `DeployerCannotPayGas(deployer, 0, 1e15)` below
**0.001 ETH**. I hit this running the dry run. 0.0012 clears it, and the gas it
actually needs is $0.35 of the $2.26 allocated.

**The agent gets the most because it is the one that cannot be topped up
mid-demo without someone noticing.** An unfunded agent is a failure this repo
has already had: `/health` green on all three seams, the model reasoning
correctly, all six validation layers passing, and only the broadcast failing
with `-32003`. `scripts/preflight.sh` now gates on it, but the gate tells you
after the fact.

### Order of operations, when you sign off

1. Swap **0.0056 ETH → USDC** on the funder. Do this first — it is the only step
   with market risk, and if the route is bad you will want to know before the
   ETH is split three ways.
2. Send **0.0012 ETH** to the deployer.
3. Send **0.0020 ETH** to the agent.
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
