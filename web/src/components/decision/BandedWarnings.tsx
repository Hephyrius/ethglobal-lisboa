import type { AgentAction } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'

/**
 * Constraints this cycle bent and was accepted anyway.
 *
 * Wave 2 gave mandates a `tolerance_band_pct`: a decision that breaches a
 * numeric constraint by no more than the band is accepted with a recorded
 * warning rather than rejected, because landing at 61% against a 60% cap is
 * usually a swap that priced a hair differently, not a change of intent.
 *
 * **That only stays defensible if it is visible.** A band nobody can see is
 * indistinguishable from there being no rule — and worse, it is how an agent
 * drifts: accept 5% over, tick after tick, and the book walks away from the
 * mandate without a single rejection to show for it. So this renders on the
 * action itself, next to the reasoning that produced it.
 *
 * Styled as an *accepted exception*, not a failure. The decision executed; the
 * warning is the receipt. Colouring it like an error would teach a reader to
 * scan past red as noise, which is exactly what must not happen to the
 * `rejected` cards this feed also carries.
 */
export function BandedWarnings({ warnings }: { warnings: AgentAction['warnings'] }) {
  if (!warnings || warnings.length === 0) return null

  return (
    <div className="mt-4 rounded border border-warn/25 bg-warn/[0.06] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="warn">ACCEPTED WITHIN BAND</Badge>
        <span className="text-2xs text-warn/80">
          {warnings.length} constraint{warnings.length === 1 ? '' : 's'} bent, not breached
        </span>
      </div>

      <ul className="mt-2 space-y-2">
        {warnings.map((warning, index) => (
          <li key={`${warning.constraint}-${warning.subject ?? ''}-${index}`}>
            <p className="text-2xs leading-relaxed text-warn/90">{warning.message}</p>
            <p className="tabular mt-0.5 font-mono text-2xs text-warn/70">
              {warning.constraint}
              {warning.subject ? ` · ${warning.subject}` : ''} — limit {format(warning.limit)}, actual{' '}
              {format(warning.actual)}, band ±{Math.round(warning.band_pct * 100)}%
            </p>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * These arrive as fractions for percentage-style constraints and as whole
 * numbers for counts, and the schema does not say which is which. Values at or
 * below 1 render as percentages — wrong only for a limit that is genuinely the
 * count "1", where "100%" is still readable rather than misleading.
 */
function format(value: number): string {
  return value <= 1 ? `${(value * 100).toFixed(1)}%` : String(value)
}
