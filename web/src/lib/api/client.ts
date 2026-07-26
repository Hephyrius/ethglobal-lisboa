import type { ZodType, ZodTypeDef } from 'zod'
import { API_BASE } from './routes'

/**
 * A zod schema constrained on its *output* type only.
 *
 * `ZodType<T>` defaults to `ZodType<T, ZodTypeDef, T>` — input and output both
 * pinned to T. Our schemas use `.default()`, so their input and output types
 * genuinely differ (`max_position_pct?: number` in, `number` out) and TS
 * resolves the ambiguity by inferring the *input* side. Every parsed value then
 * gets typed with optional fields that zod has in fact already filled in.
 * Leaving the input parameter as `unknown` makes T unambiguously the output.
 */
type SchemaOf<T> = ZodType<T, ZodTypeDef, unknown>

/**
 * The fetch layer, and the single most important design decision in this lane.
 *
 * Lane E must never be blocked on Lane B (master plan §10), so every call falls
 * back to a golden fixture when the agent API is unreachable, errors, or
 * returns something that does not match the frozen schema. But a *silent*
 * fallback is a trap: The Graph disqualifies mocked data on the demo path, and
 * the way that goes wrong is not deliberate cheating — it is standing in front
 * of a judge with fixtures on screen and believing they are live.
 *
 * So the fallback is loud. Every response carries the mode it came from, and
 * the app header renders it permanently. If it says FIXTURES during the demo,
 * we can see it from across the room.
 *
 * Falling back on *schema mismatch* is deliberate too: if Lane B drifts from
 * the frozen interface, that shows up as a visible badge and a legible zod
 * error rather than a white screen.
 */

/**
 * Where the data on screen actually came from.
 *
 * `chain` is a genuine third state, not a shade of the other two: when the
 * agent API is down we can still read the vault's own numbers straight from the
 * ERC-4626 contract, and those are *more* authoritative than the API's, not
 * less — the API is itself only reading the chain. Collapsing it into `fixture`
 * would understate the truth; collapsing it into `live` would hide that the
 * agent API is unreachable.
 */
export type SourceMode = 'live' | 'chain' | 'fixture'

export type Sourced<T> = {
  data: T
  mode: SourceMode
  /** Why we fell back. Rendered in the mode badge's tooltip. */
  note?: string
}

/** Escape hatch for demoing with no backend at all: NEXT_PUBLIC_FIXTURES=1 */
export const FIXTURES_FORCED = process.env.NEXT_PUBLIC_FIXTURES === '1'

/**
 * Long enough that a *busy* backend is not mistaken for a *dead* one.
 *
 * This was 4000ms, on the reasoning that a hung backend must not stall a demo.
 * The reasoning is right and the number was wrong, because it was never
 * measured against the load the browse page actually creates.
 *
 * That page renders every vault from the factory and issues one
 * `GET /vault/{addr}/state` per vault — twelve of them, concurrently, every
 * `VAULT_STATE_REFETCH_MS` (12s). Each of those reads ~15 `eth_call`s server
 * side. Timed against the deployed API with all twelve in flight:
 *
 *     slowest   3.48s     <- 520ms under the old ceiling
 *     median    1.72s
 *     wall      3.56s
 *
 * So the old budget cleared the worst case by half a second with nothing else
 * competing. Anything extra — the browser's own chain reads, a ticker round, a
 * slower network — pushed the tail over, and headless Chrome confirmed it:
 * sixteen `net::ERR_ABORTED` on `/state` in a thirty-second session, each one a
 * panel silently swapping to a golden fixture and back. Twelve seconds later it
 * would recover, which is what made it read as the API "disconnecting".
 *
 * A genuinely dead API does not need this budget: nothing is listening, the
 * connection is refused in milliseconds, and the fixture renders immediately.
 * The timeout only ever governs how patient we are with an API that *is*
 * answering, and there the right answer is "more patient than the slowest
 * honest response".
 */
const DEFAULT_TIMEOUT_MS = 15_000

export class ApiUnavailable extends Error {}

type FetchOptions<T> = {
  path: string
  schema: SchemaOf<T>
  /** Fixture used when the live call cannot be trusted. Lazy — never built unless needed. */
  fallback: () => T
  init?: RequestInit
  timeoutMs?: number
}

export async function apiFetch<T>({
  path,
  schema,
  fallback,
  init,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}: FetchOptions<T>): Promise<Sourced<T>> {
  if (FIXTURES_FORCED) {
    return { data: fallback(), mode: 'fixture', note: 'NEXT_PUBLIC_FIXTURES=1, forced offline mode' }
  }

  try {
    const parsed = await apiFetchStrict({ path, schema, init, timeoutMs })
    return { data: parsed, mode: 'live' }
  } catch (error) {
    return {
      data: fallback(),
      mode: 'fixture',
      note: error instanceof Error ? error.message : 'agent API unavailable',
    }
  }
}

/**
 * Same call without the fallback — throws instead.
 *
 * Used for state-changing routes (`/genesis/finalize`) where quietly returning
 * a fixture would be a lie: it would show a vault address that was never
 * deployed. Reads degrade; writes fail honestly.
 */
export async function apiFetchStrict<T>({
  path,
  schema,
  init,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}: Omit<FetchOptions<T>, 'fallback'>): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch (error) {
    const reason =
      error instanceof DOMException && error.name === 'AbortError'
        ? `agent API did not respond within ${timeoutMs}ms`
        : `cannot reach agent API at ${API_BASE}`
    throw new ApiUnavailable(reason)
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    throw new ApiUnavailable(`agent API returned ${response.status} for ${path}`)
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiUnavailable(`agent API returned a non-JSON body for ${path}`)
  }

  const result = schema.safeParse(body)
  if (!result.success) {
    const first = result.error.issues[0]
    const where = first?.path.join('.') || '(root)'
    throw new ApiUnavailable(`response did not match the frozen schema at ${where}: ${first?.message}`)
  }
  return result.data
}

export function postJson(body: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(body) }
}
