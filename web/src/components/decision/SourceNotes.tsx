import type { MarketSnapshot } from '@curator/schema'
import { isInjectionNote } from './InjectionFindings'

/**
 * Context about a source that is *not* a failure.
 *
 * The schema draws this distinction deliberately: an error is a source that
 * broke, a note is a structural non-applicability or a deliberate skip — "USDC
 * is the quote token here, so a dex price for it would be a price against
 * itself". Shown apart from `BlindSpots` for the reason the schema gives, that
 * a category mistake rendered as a gap teaches the reader to distrust a feed
 * that is working correctly.
 *
 * ⚠️ This field went unrendered from Wave 2 until Wave 3. Lane C shipped
 * diagnostic notes as a deliverable and nothing in this lane displayed them, so
 * the work was invisible on the only surface it was built for. Worth stating
 * because the failure was silent in both directions: no error, no empty state,
 * just a populated array nobody read.
 */
export function SourceNotes({ snapshot }: { snapshot: MarketSnapshot }) {
  // Security findings are elevated into their own panel. Filtered out here so
  // they are not also listed as routine diagnostics, which would read as the
  // page having shrugged at them.
  const notes = snapshot.notes.filter((note) => !isInjectionNote(note))
  if (notes.length === 0) return null

  return (
    <div className="mt-3 rounded-lg border border-line bg-raised/60 px-3 py-2.5">
      <div className="label text-faint">Noted, not missing</div>
      <ul className="mt-1.5 space-y-1">
        {notes.map((note, index) => (
          <li key={`${note.source}-${index}`} className="text-2xs leading-relaxed text-muted">
            <span className="font-mono font-medium text-faint">{note.source}</span>
            <span className="text-faint"> — </span>
            {note.message}
          </li>
        ))}
      </ul>
    </div>
  )
}
