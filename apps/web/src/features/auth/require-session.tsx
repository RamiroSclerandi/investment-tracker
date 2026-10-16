import { Navigate } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useAuthStatus } from '@/features/auth/use-auth-status'

export function RequireSession({ children }: { children: ReactNode }) {
  const status = useAuthStatus()
  if (status === 'anonymous') return <Navigate to="/login" replace />
  if (status === 'loading') {
    return (
      <div role="status" aria-label="Cargando tu sesión" className="grid min-h-svh place-items-center bg-background">
        <span className="size-6 animate-spin rounded-full border-2 border-border-strong border-t-primary" />
      </div>
    )
  }
  return children
}
