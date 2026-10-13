import { createRoute } from '@tanstack/react-router'
import { PlaceholderPage } from '@/components/placeholder-page'
import { shellRoute } from '@/routes/shell'

export const transactionsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/transactions',
  component: () => <PlaceholderPage title="Transactions" />,
})
