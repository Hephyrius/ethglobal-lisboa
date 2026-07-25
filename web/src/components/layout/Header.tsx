'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ModeBadge } from '@/components/ui/ModeBadge'
import { WalletButton } from '@/components/wallet/WalletButton'
import { networkLabel } from '@/lib/chain/explorer'
import { useAgentHealth } from '@/lib/api/health-query'
import { cn } from '@/lib/cn'

export function Header() {
  const pathname = usePathname()
  // Runs on every page: an agent that is up but internally serving fixtures
  // would otherwise sit under a confident green badge. See health-query.ts.
  useAgentHealth()

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-5 px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <Mark />
          <span className="font-serif text-base font-semibold tracking-tight text-ink">Curator</span>
          <span className="hidden border-l border-line pl-2.5 text-2xs uppercase tracking-[0.09em] text-faint sm:inline">
            Agentic vault curation
          </span>
        </Link>

        <nav className="hidden items-center gap-1 sm:flex">
          <NavLink href="/create" active={pathname === '/create'}>
            Create a vault
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-2xs text-faint md:inline">{networkLabel}</span>
          <ModeBadge />
          <WalletButton />
        </div>
      </div>
    </header>
  )
}

function NavLink({
  href,
  active,
  children,
}: {
  href: string
  active: boolean
  children: React.ReactNode
}) {
  return (
    <Link
      href={href}
      className={cn(
        'rounded px-2.5 py-1.5 text-xs transition-colors',
        active ? 'bg-raised text-ink' : 'text-muted hover:bg-raised hover:text-ink',
      )}
    >
      {children}
    </Link>
  )
}

function Mark() {
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-sm bg-agent font-serif text-xs font-semibold text-white">
      C
    </span>
  )
}
