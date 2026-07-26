'use client'

import { useMutation } from '@tanstack/react-query'
import { API_BASE, ArchetypeDeployResponse, routes } from './routes'

/**
 * One click: generate a mandate inside the archetype, check it, deploy it.
 *
 * ## Why this never falls back
 *
 * Reads on this dApp degrade down a ladder — agent API, then chain, then golden
 * fixtures. Writes do not, and this is a write: it puts a contract on a chain.
 * A fallback here would show a vault that does not exist, which is the one
 * failure a demo cannot survive. So it fails loudly and says what failed.
 *
 * ## Why there is no per-stage progress
 *
 * The endpoint is a single call and the three stages happen inside it. Nothing
 * in the browser can observe which one is running, so a stepper that advanced
 * on a timer would be animating a guess — the UI would claim to know something
 * it does not, which is the exact failure this whole product is built to avoid.
 * What is shown instead is real: the stages as a description of what this call
 * does, elapsed time while it runs, and afterwards the *evidence* of what
 * happened — how many generations the envelope rejected before one passed.
 */

export type ArchetypeDeployResult = {
  vault: `0x${string}`
  mandateName?: string
  mandateHash?: string
  txHash?: string
  /** The rotating emphasis this generation was given — why two clicks differ. */
  emphasis?: string
  attempts: number
  rejections: string[]
  elapsedMs: number
}

const DEPLOY_TIMEOUT_MS = 120_000

export function useArchetypeDeploy() {
  return useMutation({
    mutationFn: async ({
      key,
      deployer,
    }: {
      key: string
      deployer: `0x${string}`
    }): Promise<ArchetypeDeployResult> => {
      const startedAt = performance.now()

      const response = await fetch(`${API_BASE}${routes.archetypeDeploy(key)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deployer }),
        // Generation, up to N regenerations, and a deploy. Minutes would be a
        // bug, but 15s is a normal slow path and must not be reported as a
        // failure — the browser giving up on a deploy that then lands is worse
        // than waiting, because the vault exists and nothing points at it.
        signal: AbortSignal.timeout(DEPLOY_TIMEOUT_MS),
      })

      if (!response.ok) {
        throw new Error(await describeFailure(response))
      }

      const parsed = ArchetypeDeployResponse.parse(await response.json())
      return {
        vault: parsed.vault as `0x${string}`,
        mandateName: parsed.mandate?.name,
        mandateHash: parsed.mandate_hash,
        txHash: parsed.deploy_tx,
        emphasis: parsed.emphasis,
        attempts: parsed.attempts ?? 1,
        rejections: parsed.rejections,
        elapsedMs: Math.round(performance.now() - startedAt),
      }
    },
    retry: false,
  })
}

/**
 * The server's own words where it has them.
 *
 * A bounded-attempts exhaustion ("the model could not produce a mandate inside
 * this envelope") is a *result*, not an outage, and it is the interesting one:
 * it is the envelope refusing to deploy something unvetted. Flattening it to
 * "deploy failed" would hide the gate doing its job.
 */
async function describeFailure(response: Response): Promise<string> {
  const fallback = `Deploy failed (${response.status})`

  let detail: string | null = null
  try {
    const body = await response.json()
    detail = typeof body?.detail === 'string' ? body.detail : null
  } catch {
    detail = null
  }

  // FastAPI answers an unrouted path with a JSON body of exactly
  // `{"detail":"Not Found"}`, so parsing the body first and trusting `detail`
  // surfaces the literal string "Not Found" — which tells a reader nothing and
  // looks like the *archetype* was not found rather than the route. Checked
  // before the detail is used, and narrowed to that exact default so a real
  // handler's 404 ("no such archetype") still speaks for itself.
  if (response.status === 404 && (detail === null || detail === 'Not Found')) {
    return 'The agent API has no archetype deploy route yet. Lane B §B1 has not shipped it.'
  }

  return detail ?? fallback
}
