import Link from 'next/link'
import { SiegeMotif } from '@/components/hero/SiegeMotif'
import { BuiltWith } from '@/components/layout/BuiltWith'
import { PortfolioStrip } from '@/components/portfolio/PortfolioStrip'
import { DeployedVaults } from '@/components/portfolio/DeployedVaults'
import { VaultList } from '@/components/vault/VaultList'

export default function HomePage() {
  return (
    <div className="space-y-14">
      {/* The motif is a flex sibling of the copy, not an absolutely-positioned
          background. Anchoring it to the right edge meant the gap to the text
          shrank as the window narrowed — 166px at 1440, but 10px at 1180, where
          it crowded the paragraph. As a flex item the gap is set once and holds
          at every width. */}
      <section className="border-b border-line pb-12 pt-4">
        <div className="lg:flex lg:items-center lg:gap-8 xl:gap-14">
          <div className="max-w-3xl">
            <p className="label">ETHGlobal Lisbon 2026</p>
            {/* No hyphen in "Agent Curated", so the nowrap that used to hold the
                compound together is gone with it — an unhyphenated pair breaks
                between words like any other phrase. */}
            <h1 className="mt-4 text-4xl leading-[1.15] tracking-tight text-ink sm:text-5xl">
              Scipio: Agent Curated Vaults
            </h1>
            <p className="mt-5 max-w-2xl text-[0.95rem] leading-relaxed text-muted">
              Build and deploy your Scipio Agent Curated Vault. It reads live markets, forms a
              thesis, and signs its own transactions out of an ERC-4626 vault. After genesis, no one
              intervenes, including you. What replaces control is visibility: the data it consulted,
              the reasoning it produced, and the transaction it sent, all in the open.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-4">
              <Link
                href="/create"
                className="inline-flex h-9 items-center rounded bg-agent px-5 text-sm font-medium text-white transition-colors hover:bg-agent/90"
              >
                Create a vault
              </Link>
            </div>
          </div>

          <SiegeMotif />
        </div>
      </section>

      {/* The logo strip is a thin band of chrome, not a section in its own
          right, so the page's 56px rhythm leaves it marooned in white space.
          Both sides are pulled in to 32px — `!` because `space-y-14` on the
          parent sets these margins via `> * + *`, which outranks a plain
          utility. */}
      <BuiltWith className="!mt-8" />

      {/* The rule sits above the heading rather than under it: it closes the
          "Built with" strip off and the title then opens the section beneath
          it, instead of the title carrying an underline of its own. */}
      <section className="!mt-8 border-t border-line pt-6">
        <h2 className="text-xl font-semibold tracking-tight text-ink">Featured Vaults</h2>
        <div className="mt-6">
          <VaultList />
        </div>
      </section>

      {/* Below the vault list so the vaults sit directly under the hero. Both
          render nothing at all when no wallet is connected — an empty panel
          captioned "connect a wallet" occupies the space a reader is scanning
          for content, which is worse than no panel.

          Two panels rather than one merged list, deliberately: shares held and
          vaults deployed are different claims about someone, and an archetype
          vault appears only in the second until it is funded — which is exactly
          the case the branch's one-click archetype flow produces. */}
      <div className="space-y-4">
        <PortfolioStrip />
        <DeployedVaults />
      </div>
    </div>
  )
}
