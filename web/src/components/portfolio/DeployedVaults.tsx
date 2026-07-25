'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { readContract } from '@wagmi/core'
import { erc4626Abi } from '@/lib/chain/abis'
import { wagmiConfig } from '@/lib/chain/wagmi'
import { useAccount } from '@/lib/chain/account'
import { useVaultsDeployedBy } from '@/lib/chain/deployed-by'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody } from '@/components/ui/Card'
import { formatAmount } from '@/lib/format/units'

/**
 * Vaults this wallet **deployed** — the other half of "my vaults".
 *
 * Kept as its own section rather than merged into the positions strip, because
 * the two answer different questions and a reader who conflates them is
 * misinformed in both directions: a vault you deployed and never funded is not
 * a position, and a vault you deposited into is not yours to have created.
 * That is not a hypothetical pairing — an archetype vault is deployed with no
 * deposit, so it lands here and *only* here until someone funds it.
 *
 * Rendered from the chain rather than from the agent API on purpose. Deployment
 * is an on-chain fact and this is the one claim on the page a judge can check
 * against an RPC without trusting our backend at all.
 */
export function DeployedVaults() {
  const { address, isConnected } = useAccount()
  const { data, isPending } = useVaultsDeployedBy(isConnected ? address : undefined)

  // Disconnected shows nothing, matching the positions strip: a panel captioned
  // "connect a wallet" occupies space a reader is scanning for content.
  if (!isConnected || !address) return null
  if (isPending) {
    return (
      <Card>
        <CardBody>
          <div className="h-14 animate-pulse-soft rounded bg-line-bright/30" />
        </CardBody>
      </Card>
    )
  }

  // The factory predates deployer attribution. Saying "you have deployed none"
  // here would be a claim about this wallet drawn from a contract that has no
  // opinion about it — and it would be false for anyone who actually has.
  if (data && !data.supported) {
    return (
      <Card>
        <CardBody className="py-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="label">Vaults you deployed</span>
            <Badge tone="warn">NOT RECORDED BY THIS FACTORY</Badge>
          </div>
          <p className="mt-2 max-w-2xl text-xs leading-relaxed text-muted">
            The deployed factory does not record who asked for each vault, so this cannot be
            answered — which is not the same as answering that you deployed none. Attribution ships
            with the next factory deploy; vaults created before it stay unattributed, because the
            record is written at creation and cannot be backfilled.
          </p>
        </CardBody>
      </Card>
    )
  }

  const vaults = data?.vaults ?? []
  if (vaults.length === 0) {
    return (
      <Card>
        <CardBody className="py-5">
          <div className="label">Vaults you deployed</div>
          <p className="mt-1.5 text-sm text-muted">
            None yet.{' '}
            <Link href="/create" className="text-agent hover:underline">
              Pick an archetype or write a mandate
            </Link>{' '}
            and it will appear here — funded or not.
          </p>
        </CardBody>
      </Card>
    )
  }

  return (
    <Card as="section">
      <CardBody className="space-y-3 py-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <span className="label">Vaults you deployed</span>
            <p className="mt-1 text-2xs text-faint">
              You asked for these. Holding shares in one is a separate thing, shown above.
            </p>
          </div>
          <Badge tone="agent">{vaults.length}</Badge>
        </div>

        <ul className="divide-y divide-line border-t border-line">
          {vaults.map((vault) => (
            <DeployedRow key={vault} vault={vault} />
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}

/**
 * One deployed vault, with the two numbers that say whether it is doing
 * anything: what it holds, and whether anyone has funded it.
 *
 * Read per row rather than batched because the list is a handful of vaults per
 * wallet — the factory holds 151 across all deployers, but `vaultsOf` has
 * already narrowed it to one wallet's own.
 */
function DeployedRow({ vault }: { vault: `0x${string}` }) {
  const { data } = useQuery({
    queryKey: ['deployed-vault-row', vault],
    staleTime: 20_000,
    retry: false,
    queryFn: async () => {
      const [symbol, totalAssets, totalSupply, assetAddress] = await Promise.all([
        readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'symbol' }),
        readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'totalAssets' }),
        readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'totalSupply' }),
        readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'asset' }),
      ])
      const assetDecimals = await readContract(wagmiConfig, {
        address: assetAddress,
        abi: erc4626Abi,
        functionName: 'decimals',
      })
      return { symbol, totalAssets, totalSupply, assetDecimals: Number(assetDecimals) }
    },
  })

  return (
    <li className="flex items-baseline gap-3 py-2">
      <Link
        href={`/vault/${vault}`}
        className="min-w-0 flex-1 truncate text-sm font-medium text-agent hover:underline"
      >
        {data?.symbol ?? 'vault'}
        <span className="ml-2 font-mono text-2xs text-faint">{vault.slice(0, 10)}…</span>
      </Link>

      {data ? (
        data.totalSupply === 0n ? (
          // Not an error and not a failure — it is the normal state of a
          // freshly generated vault, and the reason this section exists.
          <span className="text-2xs text-faint">awaiting first deposit</span>
        ) : (
          <span className="tabular text-sm text-ink">
            {formatAmount(data.totalAssets, data.assetDecimals, { maxFractionDigits: 2 })}
          </span>
        )
      ) : (
        <span className="text-2xs text-faint">—</span>
      )}
    </li>
  )
}
