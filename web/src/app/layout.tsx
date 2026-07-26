import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { Providers } from './providers'
import { Disclaimer } from '@/components/layout/Disclaimer'
import { Header } from '@/components/layout/Header'
import './globals.css'

/**
 * Where relative metadata URLs resolve from. Next needs an absolute origin to
 * emit `og:image`, and without one it warns at build time and falls back to
 * localhost — which is what a shared link would then try to load the card from.
 *
 * The deployment target per `deploy/Caddyfile`, overridable so a preview build
 * advertises its own origin rather than production's.
 */
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://scipio.capital'

/**
 * The description is deliberately one claim rather than a feature list: it is
 * the line that appears under the title in a link preview, in search results
 * and in a bookmark, and in each of those it is competing for a glance.
 *
 * `opengraph-image.tsx` and `twitter-image.tsx` supply the card art through the
 * file convention, so `openGraph.images` is not set here — declaring it would
 * override them.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: 'Scipio: Agentic Vault Curation',
    // Subpages set only their own name; this keeps the brand on the tab and in
    // any preview that reads the title alone.
    template: '%s · Scipio',
  },
  description:
    'An ERC-4626 vault curated by an autonomous agent. It reads live markets, forms a thesis under a mandate fixed at genesis, and signs its own transactions.',
  applicationName: 'Scipio',
  openGraph: {
    type: 'website',
    siteName: 'Scipio',
    url: SITE_URL,
    title: 'Scipio: Agentic Vault Curation',
    description:
      'An ERC-4626 vault curated by an autonomous agent. It reads live markets, forms a thesis under a mandate fixed at genesis, and signs its own transactions.',
    locale: 'en_GB',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Scipio: Agentic Vault Curation',
    description:
      'An ERC-4626 vault curated by an autonomous agent. It reads live markets, forms a thesis under a mandate fixed at genesis, and signs its own transactions.',
  },
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
