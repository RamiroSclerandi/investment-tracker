import { createRoute } from '@tanstack/react-router'
import { AppShell } from '@/components/app-shell'
import { RequireSession } from '@/features/auth/require-session'
import { rootRoute } from '@/routes/__root'

export const shellRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'shell',
  component: () => (
    <RequireSession>
      <AppShell />
    </RequireSession>
  ),
})
