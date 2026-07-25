'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ModeBadge } from '@/components/ui/ModeBadge'
import { WalletButton } from '@/components/wallet/WalletButton'
import { networkLabel } from '@/lib/chain/explorer'
import { cn } from '@/lib/cn'

export function Header() {
  const pathname = usePathname()

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-base/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-4 px-5">
        <Link href="/" className="group flex items-center gap-2.5">
          <Mark />
          <span className="text-sm font-semibold tracking-tight text-ink">
            Curator
            <span className="ml-1.5 font-normal text-faint transition-colors group-hover:text-muted">
              agentic vaults
            </span>
          </span>
        </Link>

        <nav className="ml-2 hidden items-center gap-1 sm:flex">
          <NavLink href="/create" active={pathname === '/create'}>
            Create a vault
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-2.5">
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
        'rounded-lg px-2.5 py-1.5 text-xs transition-colors',
        active ? 'bg-raised text-ink' : 'text-muted hover:bg-raised hover:text-ink',
      )}
    >
      {children}
    </Link>
  )
}

function Mark() {
  return (
    <span className="relative flex h-6 w-6 items-center justify-center rounded-md border border-agent/40 bg-agent/10">
      <span className="h-1.5 w-1.5 rounded-full bg-agent" />
      <span className="absolute inset-0 rounded-md ring-1 ring-inset ring-agent/10" />
    </span>
  )
}
