import Link from 'next/link'
import { VaultDashboard } from '@/components/vault/VaultDashboard'
import { asAddress } from '@/lib/chain/deployments'

export default function VaultPage({ params }: { params: { address: string } }) {
  const address = asAddress(params.address)

  if (!address) {
    return (
      <div className="mx-auto max-w-lg py-20 text-center">
        <h1 className="text-lg font-semibold text-ink">Not a vault address</h1>
        <p className="mt-2 text-sm text-muted">
          <span className="font-mono text-xs">{params.address}</span> is not a 20-byte hex address.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block text-sm text-agent underline-offset-4 hover:underline"
        >
          ← Back to vaults
        </Link>
      </div>
    )
  }

  return <VaultDashboard address={address} />
}
