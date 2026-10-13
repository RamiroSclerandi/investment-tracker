import { createRoute } from '@tanstack/react-router'
import { rootRoute } from '@/routes/__root'

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: () => <h1 className="p-4 text-xl font-semibold">Investment Tracker</h1>,
})
