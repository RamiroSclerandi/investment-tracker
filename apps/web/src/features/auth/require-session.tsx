import { Navigate } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { refreshSession } from '@/features/auth/session'
import { useAuthStatus } from '@/features/auth/use-auth-status'

export function RequireSession({ children }: { children: ReactNode }) {
  const status = useAuthStatus()
  if (status === 'anonymous') return <Navigate to="/login" replace />
  if (status === 'unavailable') return <UnavailableState />
  if (status === 'loading') {
    return (
      <div role="status" aria-label="Cargando tu sesión" className="grid min-h-svh place-items-center bg-background">
        <span className="size-6 animate-spin rounded-full border-2 border-border-strong border-t-primary" />
      </div>
    )
  }
  return children
}

function UnavailableState() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-5 bg-background p-6 text-center text-foreground">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">No pudimos conectar</h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">Revisá tu conexión y volvé a intentarlo.</p>
      </div>
      <button
        type="button"
        onClick={() => void refreshSession()}
        className="h-[52px] w-full max-w-xs rounded-[14px] bg-primary text-base font-semibold text-primary-foreground"
      >
        Reintentar
      </button>
    </main>
  )
}
