import createClient from 'openapi-fetch'
import type { paths } from '@/api/generated/schema'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

const CSRF_HEADER = { 'x-requested-with': 'investment-tracker' }
const REFRESH_LOCK = 'it-refresh'

// Separate client without the auth middleware, so a failing refresh can never trigger another refresh.
const sessionClient = createClient<paths>({ baseUrl: window.location.origin })

let accessToken: string | null = null
let status: AuthStatus = 'loading'
let pendingRefresh: Promise<boolean> | null = null
const listeners = new Set<() => void>()

export function getAccessToken(): string | null {
  return accessToken
}

export function getAuthStatus(): AuthStatus {
  return status
}

export function subscribeAuthStatus(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function setAccessToken(token: string | null) {
  accessToken = token
  const nextStatus = token === null ? 'anonymous' : 'authenticated'
  if (nextStatus === status) return
  status = nextStatus
  listeners.forEach((listener) => listener())
}

// Tabs refreshing at once would present the same it_rt; the API treats the second as reuse and revokes the family.
function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  if (!('locks' in navigator)) return task()
  return navigator.locks.request(REFRESH_LOCK, task)
}

async function requestAccessToken(): Promise<boolean> {
  try {
    const { data } = await withRefreshLock(() =>
      sessionClient.POST('/api/v1/auth/refresh', {
        params: { header: CSRF_HEADER },
        credentials: 'same-origin',
      }),
    )
    setAccessToken(data?.access_token ?? null)
  } catch (error) {
    if (!(error instanceof TypeError)) throw error
    setAccessToken(null)
  }
  return accessToken !== null
}

export function refreshSession(): Promise<boolean> {
  pendingRefresh ??= requestAccessToken().finally(() => {
    pendingRefresh = null
  })
  return pendingRefresh
}

export async function logout(): Promise<void> {
  try {
    await sessionClient.POST('/api/v1/auth/logout', {
      params: { header: CSRF_HEADER },
      credentials: 'same-origin',
    })
  } finally {
    setAccessToken(null)
  }
}
