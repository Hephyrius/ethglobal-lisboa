'use client'

import { useQuery } from '@tanstack/react-query'
import { apiFetchStrict, FIXTURES_FORCED } from './client'
import { routes, schemas } from './routes'
import { useDataMode } from './mode-context'
import { useEffect } from 'react'

/**
 * `GET /health` — and the reason it is worth a dedicated query.
 *
 * The mode badge catches the obvious failure: the agent API is unreachable, so
 * we fell back to fixtures. It cannot catch the *subtle* one, which Lane B
 * flagged directly: the API can be up, healthy and answering every route
 * perfectly while itself running in fixture mode. Every response would then be
 * schema-valid, every request would succeed, and the badge would sit on a
 * confident green LIVE over numbers that came out of
 * `packages/schema/fixtures` on the other side of the wire.
 *
 * That is the deepest version of exactly the trap the badge exists to prevent,
 * so the health check is folded into the same aggregate: if the agent reports
 * `mode: "fixture"`, this page is showing fixtures no matter how well the
 * requests went, and the badge says so.
 */
export function useAgentHealth() {
  const { report } = useDataMode()

  const query = useQuery({
    queryKey: ['agent-health'],
    enabled: !FIXTURES_FORCED,
    retry: false,
    refetchInterval: 30_000,
    staleTime: 20_000,
    queryFn: () =>
      apiFetchStrict({
        path: routes.health(),
        schema: schemas.health.response,
        timeoutMs: 3000,
      }),
  })

  const health = query.data
  const isFailed = query.isError

  useEffect(() => {
    // Only *worsen* the aggregate. If health is unreachable the individual data
    // queries already report their own fallbacks — a second amber report for
    // the same underlying outage would be noise, so silence is right here.
    if (isFailed || !health) return

    if (health.mode === 'fixture') {
      report('agent-health', {
        mode: 'fixture',
        note: 'the agent API is running in fixture mode and is serving golden fixtures itself',
      })
    } else if (health.status === 'degraded') {
      report('agent-health', {
        mode: 'fixture',
        note: `the agent reports itself degraded${
          health.model_reachable === false ? ', the model is not reachable or not pulled' : ''
        }`,
      })
    } else {
      report('agent-health', { mode: 'live' })
    }
  }, [health, isFailed, report])

  return query
}
