'use client'

import { useQuery } from '@tanstack/react-query'
import type { z } from 'zod'
import { apiFetchStrict, FIXTURES_FORCED } from './client'
import { routes, schemas } from './routes'
import { useGenesisSources } from './genesis-queries'

export type VenueRow = z.infer<typeof schemas.venues.response>[number]

/**
 * Lane D's venue capability manifest, degrading to bare keys.
 *
 * The manifest exists (`from venues import manifest`, note #61) but nothing
 * serves it over HTTP yet — requested from Lane B in note #68. Rather than wait,
 * this asks for the route and falls back to the venue keys `GET /genesis/sources`
 * already returns, marking the rows as unenriched.
 *
 * The fallback is deliberately *keys only*, with no invented capability text.
 * Guessing that `aqua` is virtual would be right today and is exactly the habit
 * that hid the fully-built Aave venue for a wave: a description written here
 * cannot know what the registry actually holds. Better to render a venue with
 * nothing more than its name than to render a confident description of a venue
 * that has changed underneath us.
 */
export function useVenueManifest(): { rows: VenueRow[]; enriched: boolean } {
  const available = useGenesisSources()

  const query = useQuery({
    queryKey: ['venue-manifest'],
    enabled: !FIXTURES_FORCED,
    retry: false,
    staleTime: 60_000,
    queryFn: () =>
      apiFetchStrict({
        path: routes.venues(),
        schema: schemas.venues.response,
        timeoutMs: 4000,
      }),
  })

  if (query.data && query.data.length > 0) {
    return { rows: query.data, enriched: true }
  }

  return {
    rows: available.venues.map((key) => ({
      key,
      intents: [],
      tokens: [],
      requires: [],
      available: true,
    })),
    enriched: false,
  }
}
