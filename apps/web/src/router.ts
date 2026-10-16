import { createRouter, type RouterHistory } from '@tanstack/react-router'
import { rootRoute } from '@/routes/__root'
import { authLayoutRoute, authRoutes } from '@/routes/auth'
import { indexRoute } from '@/routes/index'
import { shellRoute } from '@/routes/shell'
import { transactionsRoute } from '@/routes/transactions'

const routeTree = rootRoute.addChildren([
  shellRoute.addChildren([indexRoute, transactionsRoute]),
  authLayoutRoute.addChildren(authRoutes),
])

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, ...(history ? { history } : {}) })
}

export type AppRouter = ReturnType<typeof createAppRouter>

export const router = createAppRouter()

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
