'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Mandate, type Mandate as MandateT } from '@curator/schema'
import { Button } from '@/components/ui/Button'
import { Card, CardBody } from '@/components/ui/Card'
import { useGenesisFinalize } from '@/lib/api/genesis-queries'
import { API_BASE } from '@/lib/api/routes'
import { FIXTURE_VAULT_STATE } from '@/lib/api/fixtures'
import { rememberVault } from '@/lib/mandate/store'

/**
 * Deploy the mandate.
 *
 * `POST /genesis/finalize` has **no fixture fallback** — see genesis-queries.ts.
 * Every read in this app degrades to a fixture so nothing is ever blocked, but
 * a deploy that quietly returned one would hand back a vault address that was
 * never deployed and a transaction hash that does not exist. Reads degrade;
 * writes fail honestly.
 *
 * When it does fail, the mandate stays on screen and we offer a clearly-labelled
 * fixture preview of the vault surface instead — so the flow is still
 * demonstrable end to end without ever showing a fabricated deployment.
 */
export function DeployPanel({ draft }: { draft: Partial<MandateT> }) {
  const router = useRouter()
  const finalize = useGenesisFinalize()

  const parsed = Mandate.safeParse(draft)
  const missing = parsed.success ? [] : missingFields(parsed.error.issues)

  async function deploy() {
    if (!parsed.success) return

    const mandate = parsed.data
    const result = await finalize.mutateAsync(mandate).catch(() => null)
    if (!result) return

    rememberVault(
      {
        address: result.vault,
        name: mandate.name,
        mandateHash: result.mandate_hash,
        deployTx: result.deploy_tx,
        createdAt: new Date().toISOString(),
      },
      mandate,
    )
    router.push(`/vault/${result.vault}`)
  }

  return (
    <Card className="border-agent/20 bg-agent/[0.03]">
      <CardBody className="space-y-3">
        <Button
          variant="primary"
          className="w-full"
          loading={finalize.isPending}
          disabled={!parsed.success}
          onClick={() => void deploy()}
        >
          {finalize.isPending ? 'Deploying vault…' : 'Deploy vault'}
        </Button>

        {!parsed.success ? (
          <p className="text-2xs leading-relaxed text-faint">
            Still needed: {missing.join(', ')}. Keep talking to the curator.
          </p>
        ) : (
          <p className="text-2xs leading-relaxed text-muted">
            Deploying crystallises this mandate at genesis and hands the vault to the agent. You
            will not be able to change it afterwards.
          </p>
        )}

        {finalize.isError ? (
          <div className="rounded-lg border border-bad/25 bg-bad/[0.05] px-3 py-2.5">
            <p className="text-2xs font-medium text-bad">Deploy failed — nothing was deployed.</p>
            <p className="mt-1 text-2xs leading-relaxed text-bad/80">
              {finalize.error instanceof Error ? finalize.error.message : 'Unknown error'}
            </p>
            <p className="mt-2 text-2xs leading-relaxed text-muted">
              The agent API at <span className="font-mono">{API_BASE}</span> has to be running to
              deploy. We will not invent a vault address for you — but you can{' '}
              <Link
                href={`/vault/${FIXTURE_VAULT_STATE.address}`}
                className="text-agent underline-offset-2 hover:underline"
              >
                preview the vault surface with fixture data
              </Link>
              .
            </p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}

/** Turn zod issues into the plain-language list of what the conversation still owes us. */
function missingFields(issues: { path: (string | number)[] }[]): string[] {
  const LABELS: Record<string, string> = {
    objective: 'an objective',
    name: 'a name',
    base_asset: 'a base asset',
    constraints: 'risk limits',
    permitted_data_sources: 'data sources',
    permitted_venues: 'execution venues',
    // `version` is deliberately absent: it is a schema field the harness sets,
    // not something the user can answer, so listing it as "still needed" would
    // ask them for something they cannot provide.
  }
  const seen = new Set<string>()
  for (const issue of issues) {
    const root = String(issue.path[0] ?? '')
    if (LABELS[root]) seen.add(LABELS[root])
  }
  return seen.size > 0 ? [...seen] : ['more detail']
}
