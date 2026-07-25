import Link from 'next/link'
import { PortfolioStrip } from '@/components/portfolio/PortfolioStrip'
import { VaultList } from '@/components/vault/VaultList'

export default function HomePage() {
  return (
    <div className="space-y-14">
      <section className="border-b border-line pb-12 pt-4">
        <p className="label">ETHGlobal Lisbon 2026</p>
        <h1 className="mt-4 max-w-3xl text-4xl leading-[1.15] tracking-tight text-ink sm:text-5xl">
          {/* nowrap so the compound never splits across lines at its hyphen,
              which at this size reads as "Agent-" hanging on the first line. */}
          Curator: Design and Deploy <span className="whitespace-nowrap">Agent-Curated</span> Vaults
        </h1>
        <p className="mt-5 max-w-2xl text-[0.95rem] leading-relaxed text-muted">
          You write the mandate. Your Curator Agent does the rest, reading live markets, forming a
          thesis, and signing its own transactions out of an ERC-4626 vault. After genesis, no one
          intervenes, including you. What replaces control is visibility: the data it consulted, the
          reasoning it produced, and the transaction it sent, all in the open.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-4">
          <Link
            href="/create"
            className="inline-flex h-9 items-center rounded bg-agent px-5 text-sm font-medium text-white transition-colors hover:bg-agent/90"
          >
            Create a vault
          </Link>
        </div>
      </section>

      <section>
        <div className="flex items-baseline justify-between border-b border-line pb-2">
          <h2 className="text-xl font-semibold tracking-tight text-ink">Explore Deployed Vaults</h2>
          <Link href="/create" className="text-xs text-muted transition-colors hover:text-ink">
            Create a vault →
          </Link>
        </div>
        <div className="mt-6">
          <VaultList />
        </div>
      </section>

      {/* Below the vault list so the vaults sit directly under the hero. Renders
          nothing at all when no wallet is connected — an empty panel captioned
          "connect a wallet" occupies the space a reader is scanning for content,
          which is worse than no panel. */}
      <PortfolioStrip />
    </div>
  )
}
