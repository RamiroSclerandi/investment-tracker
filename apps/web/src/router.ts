import { createRouter } from '@tanstack/react-router'
import { rootRoute } from '@/routes/__root'
import { authLayoutRoute, authRoutes } from '@/routes/auth'
import { indexRoute } from '@/routes/index'
import { shellRoute } from '@/routes/shell'
import { transactionsRoute } from '@/routes/transactions'

export const router = createRouter({
  routeTree: rootRoute.addChildren([
    shellRoute.addChildren([indexRoute, transactionsRoute]),
    authLayoutRoute.addChildren(authRoutes),
  ]),
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
