import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { Providers } from './providers'
import { Disclaimer } from '@/components/layout/Disclaimer'
import { Header } from '@/components/layout/Header'
import './globals.css'

export const metadata: Metadata = {
  title: 'Curator — agentic vault curation',
  description:
    'An ERC-4626 vault curated by an autonomous LLM agent. Watch it consult live market data, reason under its mandate, and execute on-chain.',
}

export const viewport = {
  // Without this a phone renders the page at a 980px virtual width and scales
  // it down, so every breakpoint below `lg` never fires and the "responsive"
  // layout is simply a shrunken desktop one.
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Providers>
          <Disclaimer />
          <Header />
          <main className="mx-auto max-w-[1400px] px-4 pb-20 pt-6 sm:px-6 sm:pb-24 sm:pt-8">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  )
}
