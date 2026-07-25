import Link from 'next/link'
import { VaultList } from '@/components/vault/VaultList'

export default function HomePage() {
  return (
    <div className="space-y-16">
      <section className="pt-6">
        <p className="label">ETHGlobal Lisbon 2026</p>
        <h1 className="mt-4 max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight text-ink sm:text-5xl">
          The curator is an{' '}
          <span className="text-agent">agent</span>.
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-relaxed text-muted">
          An ERC-4626 vault whose allocation decisions are made by an autonomous LLM working under a
          mandate you write in plain language. It reads live market data, decides, and executes with
          its own key. There is no human override after genesis — so every decision it makes is shown
          in full: the data it consulted, the reasoning it produced, and the transaction it sent.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link
            href="/create"
            className="inline-flex h-10 items-center rounded-lg bg-agent px-5 text-sm font-semibold text-base transition-colors hover:bg-agent/90"
          >
            Create a vault
          </Link>
          <span className="text-xs text-faint">
            Genesis takes about a minute — a conversation, then a deploy.
          </span>
        </div>
      </section>

      <section>
        <h2 className="label">What you will see</h2>
        <div className="mt-4 grid gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-3">
          <Step
            index="01"
            accent="text-data"
            title="Data consulted"
            body="Every fact the agent read, with the source that reported it and when. A source that failed is shown too — what the agent could not see shapes what it decided."
          />
          <Step
            index="02"
            accent="text-agent"
            title="Reasoning"
            body="The curator's own words, verbatim, alongside the exact facts it cited. If it cites a number that was not in its snapshot, that is visible rather than hidden."
          />
          <Step
            index="03"
            accent="text-ok"
            title="Execution"
            body="The calldata it sent and the transaction hash it landed. Rotation through Uniswap; positions held in 1inch Aqua, where the tokens never leave the vault."
          />
        </div>
      </section>

      <section>
        <div className="flex items-baseline justify-between">
          <h2 className="label">Vaults</h2>
          <Link href="/create" className="text-xs text-muted transition-colors hover:text-ink">
            Create a vault →
          </Link>
        </div>
        <div className="mt-4">
          <VaultList />
        </div>
      </section>
    </div>
  )
}

function Step({
  index,
  title,
  body,
  accent,
}: {
  index: string
  title: string
  body: string
  accent: string
}) {
  return (
    <div className="bg-surface p-6">
      <div className={`font-mono text-xs ${accent}`}>{index}</div>
      <h3 className="mt-3 text-sm font-semibold text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
    </div>
  )
}
