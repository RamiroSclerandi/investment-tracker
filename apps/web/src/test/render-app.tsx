import { createMemoryHistory } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { beforeAll, vi } from 'vitest'

// The first import transforms the whole app, which can outlast a test's default timeout on a cold run.
beforeAll(() => import('@/app'), 30_000)

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
