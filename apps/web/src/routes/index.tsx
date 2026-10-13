import { createRoute } from '@tanstack/react-router'
import { PlaceholderPage } from '@/components/placeholder-page'
import { shellRoute } from '@/routes/shell'

export const indexRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/',
  component: () => <PlaceholderPage title="Dashboard" />,
})
