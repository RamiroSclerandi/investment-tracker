import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { type AppRouter, router as defaultRouter } from '@/router'

const queryClient = new QueryClient()

export function App({ router = defaultRouter }: { router?: AppRouter }) {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
