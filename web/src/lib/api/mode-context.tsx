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

type DataModeValue = {
  mode: SourceMode
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
    return {
      // No reports yet means nothing has resolved — treat as live so the badge
      // does not flash a false warning on first paint.
      mode: degraded.length > 0 ? 'fixture' : 'live',
      notes: [...new Set(degraded.map((entry) => entry.note).filter((n): n is string => !!n))],
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
