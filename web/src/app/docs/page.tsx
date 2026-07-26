import Link from 'next/link'

/**
 * The constitutional text, moved out of the vault view.
 *
 * Wave 2 §E7: the "the agent holds AGENT_ROLE and executes directly…" paragraph
 * was sitting in the primary vault area, where it competes with the numbers a
 * reader came for. It belongs somewhere it can be read once and linked to.
 *
 * Built as a route rather than the slide-over drawer the plan sketches. A
 * drawer cannot be linked to, is awkward on a phone, and this is the page a
 * sceptical reader most wants to send to someone else. The nav link goes here
 * from every page.
 */
export const metadata = {
  title: 'How this works · Curator',
}

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-10">
      <header className="border-b border-line pb-6">
        <p className="label">Documentation</p>
        <h1 className="mt-3 font-serif text-3xl leading-tight tracking-tight text-ink sm:text-4xl">
          How this works
        </h1>
        <p className="mt-4 text-sm leading-relaxed text-muted">
          What the agent is allowed to do, where the rules that bind it are actually stored, and
          what this system deliberately does not do.
        </p>
      </header>

      <Section title="The trust model">
        <p>
          The agent holds{' '}
          <code className="rounded bg-raised px-1 py-0.5 font-mono text-2xs text-agent">
            AGENT_ROLE
          </code>{' '}
          on the vault and executes directly with its own key. <strong>There is no human override
          after genesis.</strong> The mandate is the only thing constraining it, and only the agent
          may amend it.
        </p>
        <p>
          That is a deliberate scope choice rather than an oversight. The thesis being tested is
          whether an agent can do the job a human vault curator does, and a system with a human
          veto is not testing that. The cost is that the trust model rests entirely on the agent
          and its harness, which is why every decision it makes is shown in full rather than
          summarised.
        </p>
      </Section>

      <Section title="Where the mandate lives">
        <p>
          This is the question the interface did not previously answer, and it matters more than it
          looks.
        </p>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Fact term="Off-chain" detail="The mandate itself">
            One JSON file per vault, held by the agent harness under{' '}
            <code className="font-mono text-2xs">AGENT_STATE_DIR</code>. The full text (objective,
            constraints, permitted sources and venues) never goes on-chain.
          </Fact>
          <Fact term="On-chain" detail="Its keccak hash only">
            <code className="font-mono text-2xs">mandateHash</code>, bound at deploy time and
            immutable thereafter.
          </Fact>
        </dl>
        <p>
          <strong>That hash is the depositor&apos;s entire verification handle.</strong> It is what
          lets you check that the mandate you were shown at genesis is the one the vault was
          actually deployed with. Compare the hash on the vault page against the keccak of the
          mandate text. Nothing else binds the two together.
        </p>
        <p className="text-muted">
          The honest consequence: a mandate is only as available as the harness holding it. Losing
          that state does not put the vault at risk, since custody is on-chain, but it does lose the
          human-readable rules behind the hash.
        </p>
      </Section>

      <Section title="Custody: the vault never lets go">
        <p>
          The vault is the <strong>sole custodian</strong> of everything it holds. Capital does not
          move to a strategy contract, a router, or a venue. It stays put, and{' '}
          <code className="font-mono text-2xs">totalAssets()</code> is always the truth about what
          is there.
        </p>
        <p>
          This is what makes the 1inch Aqua integration work rather than merely appear. Aqua is a
          shared-liquidity registry that tracks <em>virtual</em> balances: the vault posts a
          market-making quote as a maker, and the tokens remain in the vault until a taker actually
          fills. So a holding marked{' '}
          <span className="rounded border border-agent/25 bg-agent/[0.07] px-1 py-0.5 text-2xs text-agent">
            committed
          </span>{' '}
          is <strong>encumbered, not sent away</strong>. Reading it as &ldquo;sent away&rdquo; is
          the one misreading that would make you conclude the share price is wrong when it is
          exactly right.
        </p>
      </Section>

      <Section title="Where the numbers come from">
        <p>
          The badge in the header reports the <em>worst</em> source feeding the page, and it is
          there because the failure that matters is not a crash. It is a page that looks fine
          while showing invented data.
        </p>
        <ul className="space-y-2">
          <Provenance tone="text-ok" label="LIVE">
            The agent API is reachable and reports itself running against real data sources.
          </Provenance>
          <Provenance tone="text-data" label="ON-CHAIN">
            The agent API is unreachable, so the vault&apos;s own numbers were read straight from
            the ERC-4626 contract. Still real: the API only reads the same chain.
          </Provenance>
          <Provenance tone="text-warn" label="FIXTURES">
            Something on the page is sample data. That includes the case where the API is up and
            answering perfectly while itself running in fixture mode.
          </Provenance>
        </ul>
      </Section>

      <Section title="What this deliberately is not">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong>Not audited.</strong> These contracts were written during a hackathon and have
            never been reviewed by anyone outside the team.
          </li>
          <li>
            <strong>Not a product.</strong> There is no upgrade path, no incident response, and no
            one on call.
          </li>
          <li>
            <strong>Not protected against a bad model.</strong> Output validation rejects malformed
            and mandate-breaching decisions before they reach the chain, and rejected decisions are
            kept in the feed as evidence that the layer does something. It cannot catch a decision
            that is well-formed, permitted, and simply wrong.
          </li>
        </ul>
        <p className="rounded border border-warn/25 bg-warn/[0.06] px-4 py-3 text-warn">
          Proof of concept for ETHGlobal Lisbon. Do not deposit real funds.
        </p>
      </Section>

      <div className="border-t border-line pt-6">
        <Link href="/" className="text-sm text-agent underline-offset-4 hover:underline">
          ← Back to vaults
        </Link>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="rule-heading">{title}</h2>
      <div className="mt-4 space-y-4 text-sm leading-relaxed text-ink/90">{children}</div>
    </section>
  )
}

function Fact({
  term,
  detail,
  children,
}: {
  term: string
  detail: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded border border-line bg-raised/40 px-4 py-3">
      <dt className="label">{term}</dt>
      <dd className="mt-1 text-xs font-medium text-ink">{detail}</dd>
      <dd className="mt-1.5 text-xs leading-relaxed text-muted">{children}</dd>
    </div>
  )
}

function Provenance({
  tone,
  label,
  children,
}: {
  tone: string
  label: string
  children: React.ReactNode
}) {
  return (
    <li className="flex flex-col gap-1 sm:flex-row sm:gap-3">
      <span className={`shrink-0 font-mono text-2xs font-semibold sm:w-24 ${tone}`}>{label}</span>
      <span className="text-muted">{children}</span>
    </li>
  )
}
