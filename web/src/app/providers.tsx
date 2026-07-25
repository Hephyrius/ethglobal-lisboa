'use client'

import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { WagmiProvider } from 'wagmi'
import { wagmiConfig } from '@/lib/chain/wagmi'
import { DataModeProvider } from '@/lib/api/mode-context'

export function Providers({ children }: { children: ReactNode }) {
  // Created in state, not at module scope: a module-level client would be
  // shared across server requests and leak one visitor's cache into another's.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // apiFetch already falls back to fixtures instead of throwing, so a
            // retry would only delay the render of data we can produce now.
            retry: false,
            staleTime: 5_000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  )

  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>
        <DataModeProvider>{children}</DataModeProvider>
      </QueryClientProvider>
    </WagmiProvider>
  )
}
