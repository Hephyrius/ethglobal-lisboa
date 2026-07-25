import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { Providers } from './providers'
import { Header } from '@/components/layout/Header'
import './globals.css'

export const metadata: Metadata = {
  title: 'Curator — agentic vault curation',
  description:
    'An ERC-4626 vault curated by an autonomous LLM agent. Watch it consult live market data, reason under its mandate, and execute on-chain.',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Providers>
          <Header />
          <main className="mx-auto max-w-[1400px] px-5 pb-24 pt-8">{children}</main>
        </Providers>
      </body>
    </html>
  )
}
