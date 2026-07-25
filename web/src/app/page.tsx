import Link from 'next/link'
import { VaultList } from '@/components/vault/VaultList'

export default function HomePage() {
  return (
    <div className="space-y-14">
      <section className="border-b border-line pb-12 pt-4">
        <p className="label">ETHGlobal Lisbon 2026</p>
        <h1 className="mt-4 max-w-3xl font-serif text-4xl leading-[1.15] tracking-tight text-ink sm:text-5xl">
          The curator is an agent.
        </h1>
        <p className="mt-5 max-w-2xl text-[0.95rem] leading-relaxed text-muted">
          An ERC-4626 vault whose allocation decisions are made by an autonomous model working under
          a mandate written in plain language. It reads live market data, decides, and executes with
          its own key. There is no human override after genesis — so every decision it makes is
          shown in full: the data it consulted, the reasoning it produced, and the transaction it
          sent.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-4">
          <Link
            href="/create"
            className="inline-flex h-9 items-center rounded bg-agent px-5 text-sm font-medium text-white transition-colors hover:bg-agent/90"
          >
            Create a vault
          </Link>
          <span className="text-xs text-faint">
            Genesis takes about a minute — a conversation, then a deploy.
          </span>
        </div>
      </section>

      <section>
        <h2 className="rule-heading">The record of every decision</h2>
        <div className="mt-6 grid gap-8 md:grid-cols-3">
          <Step
            index="I"
            title="Data consulted"
            body="Every fact the agent read, with the source that reported it and when. A source that failed is shown too — what the agent could not see shapes what it decided."
          />
          <Step
            index="II"
            title="Reasoning"
            body="The curator's own words, verbatim, alongside the exact facts it cited. If it cites a figure that was not in its snapshot, that is visible rather than hidden."
          />
          <Step
            index="III"
            title="Execution"
            body="The calldata it sent and the transaction it landed. Rotation through Uniswap; positions held in 1inch Aqua, where the assets never leave the vault."
          />
        </div>
      </section>

      <section>
        <div className="flex items-baseline justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Vaults</h2>
          <Link href="/create" className="text-xs text-muted transition-colors hover:text-ink">
            Create a vault →
          </Link>
        </div>
        <div className="mt-6">
          <VaultList />
        </div>
      </section>
    </div>
  )
}

function Step({ index, title, body }: { index: string; title: string; body: string }) {
  return (
    <div>
      <div className="flex items-baseline gap-2.5 border-b border-line pb-2">
        <span className="font-serif text-sm text-agent">{index}</span>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-muted">{body}</p>
    </div>
  )
}
