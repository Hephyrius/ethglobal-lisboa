'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { SourceMode, Sourced } from './client'

/**
 * Tracks, across every query on the page, whether the data on screen came from
 * the live agent API or from a golden fixture — and surfaces the *worst* case
 * in the header.
 *
 * The aggregate matters more than any individual query: a page where the vault
 * state is live but the decision feed fell back is a page showing invented
 * decisions, and the badge has to say so. Erring toward FIXTURES is the safe
 * direction to be wrong in.
 */

type Report = { mode: SourceMode; note?: string }

/** `unknown` = nothing has loaded yet, so we cannot characterise anything. */
export type AggregateMode = SourceMode | 'unknown'

type DataModeValue = {
  mode: AggregateMode
  notes: string[]
  report: (key: string, report: Report) => void
}

const DataModeContext = createContext<DataModeValue | null>(null)

export function DataModeProvider({ children }: { children: ReactNode }) {
  const [reports, setReports] = useState<Record<string, Report>>({})

  const report = useCallback((key: string, next: Report) => {
    setReports((previous) => {
      const current = previous[key]
      if (current && current.mode === next.mode && current.note === next.note) return previous
      return { ...previous, [key]: next }
    })
  }, [])

  const value = useMemo<DataModeValue>(() => {
    const entries = Object.values(reports)
    const degraded = entries.filter((entry) => entry.mode === 'fixture')
    const fromChain = entries.filter((entry) => entry.mode === 'chain')

    // Severity order: fixture ≻ chain ≻ live. The page is only as trustworthy
    // as its least-trustworthy panel, and erring toward the worse label is the
    // safe direction to be wrong in.
    const mode: AggregateMode =
      entries.length === 0
        ? // Nothing has loaded — the landing page issues no API queries at all.
          // Claiming LIVE there would assert something about data that was
          // never fetched, so the badge renders nothing instead.
          'unknown'
        : degraded.length > 0
          ? 'fixture'
          : fromChain.length > 0
            ? 'chain'
            : 'live'

    return {
      mode,
      notes: [
        ...new Set(
          [...degraded, ...fromChain].map((entry) => entry.note).filter((n): n is string => !!n),
        ),
      ],
      report,
    }
  }, [reports, report])

  return <DataModeContext.Provider value={value}>{children}</DataModeContext.Provider>
}

export function useDataMode(): DataModeValue {
  const context = useContext(DataModeContext)
  if (!context) {
    throw new Error('useDataMode must be used inside <DataModeProvider>')
  }
  return context
}

/** Report a query's provenance into the aggregate. No-op until the query resolves. */
export function useReportMode(key: string, sourced: Sourced<unknown> | undefined): void {
  const { report } = useDataMode()
  const mode = sourced?.mode
  const note = sourced?.note

  useEffect(() => {
    if (!mode) return
    report(key, { mode, note })
  }, [key, mode, note, report])
}
