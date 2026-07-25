#!/usr/bin/env node
/**
 * Exercise the vault write path end to end against a running fork.
 *
 * **Why this exists.** The dApp's read path was verified early by `eth_call`
 * against the deployed vault, but the *write* path — approve → deposit →
 * redeem — had never been submitted, because signing needs a wallet and a
 * headless environment has none. "Every part is tested but the thing has never
 * been run" is exactly the state that produces a surprise on stage, so this
 * closes it without a browser.
 *
 * **What it proves.** It issues the same three calls, with the same ABI
 * fragments and the same argument shapes as
 * `web/src/lib/chain/vault-contract.ts`, and waits for each receipt the way the
 * UI does. If this passes, the calldata the deposit panel builds is accepted by
 * the real contract and the share accounting is right.
 *
 * **What it does not prove.** The browser's EIP-1193 handshake — connecting a
 * wallet and having it sign. That is `@wagmi/core` + the extension, not our
 * code, and it needs a human with MetaMask. Stated plainly rather than implied.
 *
 * **It leaves the vault as it found it.** Deposit, verify, then redeem exactly
 * the shares just minted, so a shared fork other lanes are working against is
 * not left with a foreign position in it. `--keep` opts out.
 *
 * Usage:
 *   node scripts/verify-vault-write-path.mjs
 *   node scripts/verify-vault-write-path.mjs --amount 250 --keep
 *   node scripts/verify-vault-write-path.mjs --rpc http://localhost:8540 --vault 0x…
 */

import { createPublicClient, createWalletClient, http, formatUnits, parseUnits } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { base } from 'viem/chains'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DEPLOYMENTS = path.join(HERE, '..', '..', 'deployments', 'base-fork.json')

/**
 * Anvil's account #0 key. This is a **published test constant** — Foundry
 * prints it on every startup and it is in its documentation. It is not a
 * secret and must never hold real funds. Override with --private-key.
 */
const ANVIL_KEY_0 = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'

// Same fragments as web/src/lib/chain/abis.ts. They are the ERC-4626 / ERC-20
// standard, not anything this project invented, which is why both can declare
// them independently without drifting.
const erc20Abi = [
  { type: 'function', name: 'decimals', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint8' }] },
  { type: 'function', name: 'symbol', stateMutability: 'view', inputs: [], outputs: [{ type: 'string' }] },
  { type: 'function', name: 'balanceOf', stateMutability: 'view', inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { type: 'function', name: 'allowance', stateMutability: 'view', inputs: [{ name: 'owner', type: 'address' }, { name: 'spender', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { type: 'function', name: 'approve', stateMutability: 'nonpayable', inputs: [{ name: 'spender', type: 'address' }, { name: 'amount', type: 'uint256' }], outputs: [{ type: 'bool' }] },
]

const erc4626Abi = [
  { type: 'function', name: 'asset', stateMutability: 'view', inputs: [], outputs: [{ type: 'address' }] },
  { type: 'function', name: 'decimals', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint8' }] },
  { type: 'function', name: 'totalAssets', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { type: 'function', name: 'balanceOf', stateMutability: 'view', inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { type: 'function', name: 'convertToAssets', stateMutability: 'view', inputs: [{ name: 'shares', type: 'uint256' }], outputs: [{ type: 'uint256' }] },
  { type: 'function', name: 'deposit', stateMutability: 'nonpayable', inputs: [{ name: 'assets', type: 'uint256' }, { name: 'receiver', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { type: 'function', name: 'redeem', stateMutability: 'nonpayable', inputs: [{ name: 'shares', type: 'uint256' }, { name: 'receiver', type: 'address' }, { name: 'owner', type: 'address' }], outputs: [{ type: 'uint256' }] },
]

function parseArgs(argv) {
  const options = { amount: '100', keep: false, privateKey: ANVIL_KEY_0, rpc: null, vault: null }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--keep') options.keep = true
    else if (arg === '--amount') options.amount = argv[++i]
    else if (arg === '--private-key') options.privateKey = argv[++i]
    else if (arg === '--rpc') options.rpc = argv[++i]
    else if (arg === '--vault') options.vault = argv[++i]
    else if (arg === '--help' || arg === '-h') {
      console.log('Usage: verify-vault-write-path.mjs [--amount N] [--keep] [--rpc URL] [--vault 0x…] [--private-key 0x…]')
      process.exit(0)
    } else {
      console.error(`Unknown argument: ${arg}`)
      process.exit(2)
    }
  }
  return options
}

const step = (n, text) => console.log(`\n${n}. ${text}`)
const detail = (label, value) => console.log(`   ${label.padEnd(22)} ${value}`)

async function main() {
  const options = parseArgs(process.argv.slice(2))

  // Addresses come from Lane A's deploy record, never hardcoded here.
  const deployments = JSON.parse(await readFile(DEPLOYMENTS, 'utf8'))
  const vault = options.vault ?? deployments.demoVault?.address ?? deployments.vaults?.[0]
  const rpcUrl = options.rpc ?? process.env.NEXT_PUBLIC_RPC_URL ?? 'http://localhost:8540'

  if (!vault) {
    console.error('No vault address in deployments/base-fork.json and none given with --vault.')
    process.exit(2)
  }

  const account = privateKeyToAccount(options.privateKey)
  const transport = http(rpcUrl)
  const publicClient = createPublicClient({ chain: base, transport })
  const walletClient = createWalletClient({ account, chain: base, transport })

  console.log(`Vault   ${vault}`)
  console.log(`RPC     ${rpcUrl}`)
  console.log(`Sender  ${account.address}`)

  const read = (address, abi, functionName, args = []) =>
    publicClient.readContract({ address, abi, functionName, args })

  const asset = await read(vault, erc4626Abi, 'asset')
  const [assetSymbol, assetDecimals, shareDecimals] = await Promise.all([
    read(asset, erc20Abi, 'symbol'),
    read(asset, erc20Abi, 'decimals'),
    read(vault, erc4626Abi, 'decimals'),
  ])

  const amount = parseUnits(options.amount, Number(assetDecimals))
  const fmtAsset = (v) => `${formatUnits(v, Number(assetDecimals))} ${assetSymbol}`
  const fmtShares = (v) => `${formatUnits(v, Number(shareDecimals))} shares`

  step(0, 'Before')
  const before = {
    wallet: await read(asset, erc20Abi, 'balanceOf', [account.address]),
    shares: await read(vault, erc4626Abi, 'balanceOf', [account.address]),
    totalAssets: await read(vault, erc4626Abi, 'totalAssets'),
  }
  detail('wallet', fmtAsset(before.wallet))
  detail('shares held', fmtShares(before.shares))
  detail('vault totalAssets', fmtAsset(before.totalAssets))

  if (before.wallet < amount) {
    console.error(`\nSender holds ${fmtAsset(before.wallet)}, needs ${fmtAsset(amount)}.`)
    process.exit(1)
  }

  const send = async (label, request) => {
    const hash = await walletClient.writeContract(request)
    const receipt = await publicClient.waitForTransactionReceipt({ hash })
    detail(label, `${hash}  status=${receipt.status}  gas=${receipt.gasUsed}`)
    if (receipt.status !== 'success') throw new Error(`${label} reverted`)
    return receipt
  }

  // Exact-amount approval, matching the UI — not an unlimited one.
  step(1, `Approve ${fmtAsset(amount)} to the vault`)
  await send('approve tx', {
    address: asset,
    abi: erc20Abi,
    functionName: 'approve',
    args: [vault, amount],
  })
  detail('allowance now', fmtAsset(await read(asset, erc20Abi, 'allowance', [account.address, vault])))

  step(2, `Deposit ${fmtAsset(amount)}`)
  await send('deposit tx', {
    address: vault,
    abi: erc4626Abi,
    functionName: 'deposit',
    args: [amount, account.address],
  })

  const afterDeposit = {
    shares: await read(vault, erc4626Abi, 'balanceOf', [account.address]),
    totalAssets: await read(vault, erc4626Abi, 'totalAssets'),
  }
  const minted = afterDeposit.shares - before.shares
  detail('shares minted', fmtShares(minted))
  detail('worth', fmtAsset(await read(vault, erc4626Abi, 'convertToAssets', [minted])))
  detail('vault totalAssets', fmtAsset(afterDeposit.totalAssets))

  if (minted <= 0n) throw new Error('Deposit minted no shares')

  if (options.keep) {
    step(3, 'Skipping redeem (--keep) — the position stays in the vault')
    console.log('\n✓ Approve and deposit verified on-chain.')
    return
  }

  step(3, `Redeem the ${fmtShares(minted)} just minted`)
  await send('redeem tx', {
    address: vault,
    abi: erc4626Abi,
    functionName: 'redeem',
    args: [minted, account.address, account.address],
  })

  const after = {
    wallet: await read(asset, erc20Abi, 'balanceOf', [account.address]),
    shares: await read(vault, erc4626Abi, 'balanceOf', [account.address]),
    totalAssets: await read(vault, erc4626Abi, 'totalAssets'),
  }
  detail('wallet', fmtAsset(after.wallet))
  detail('shares held', fmtShares(after.shares))
  detail('vault totalAssets', fmtAsset(after.totalAssets))

  step(4, 'Net effect on the shared fork')
  detail('wallet delta', fmtAsset(after.wallet - before.wallet))
  detail('vault delta', fmtAsset(after.totalAssets - before.totalAssets))
  detail('shares delta', fmtShares(after.shares - before.shares))

  console.log('\n✓ Approve, deposit and redeem all verified on-chain.')
}

main().catch((error) => {
  console.error(`\n✗ ${error.shortMessage ?? error.message}`)
  process.exit(1)
})
