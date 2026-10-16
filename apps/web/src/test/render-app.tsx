import { createMemoryHistory } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { vi } from 'vitest'

// Fresh modules per render: the router, the session store and the API client never leak between tests.
export async function renderApp(path: string) {
  vi.resetModules()
  const { createAppRouter } = await import('@/router')
  const { App } = await import('@/app')
  const session = await import('@/features/auth/session')
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  render(<App router={router} />)
  return { router, session }
}
