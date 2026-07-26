import { VaultExplorer } from '@/components/vault/VaultExplorer'

/**
 * The browse surface: every vault, searchable and filterable.
 *
 * No hero and no partner strip. This is the page a reader arrives at to find a
 * specific vault, and marketing furniture above the search box pushes the thing
 * they came for below the fold. The landing page at `/` keeps both.
 */
export const metadata = {
  title: 'Explore all vaults — Scipio',
}

export default function VaultsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
          Explore All Vaults
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          Every vault this browser can see. Search by name, address, mandate hash or objective, or
          narrow by the parameters a vault was deployed with.
        </p>
      </header>

      <VaultExplorer />
    </div>
  )
}
