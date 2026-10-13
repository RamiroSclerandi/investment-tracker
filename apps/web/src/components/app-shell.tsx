import { Link, Outlet } from '@tanstack/react-router'
import { ApiStatus } from '@/features/health/api-status'

const NAV_LINKS = [
  { to: '/', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
] as const

function PrimaryNav() {
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 border-t border-border bg-background md:static md:border-0"
    >
      <ul className="flex md:gap-2">
        {NAV_LINKS.map(({ to, label }) => (
          <li key={to} className="flex-1 md:flex-none">
            <Link
              to={to}
              activeOptions={{ exact: true }}
              className="block rounded-md px-4 py-3 text-center text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[status=active]:text-foreground"
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export function AppShell() {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3 md:px-6">
        <span className="font-semibold">Investment Tracker</span>
        <PrimaryNav />
        <ApiStatus />
      </header>
      <main className="flex-1 p-4 pb-20 md:p-6 md:pb-6">
        <Outlet />
      </main>
    </div>
  )
}
