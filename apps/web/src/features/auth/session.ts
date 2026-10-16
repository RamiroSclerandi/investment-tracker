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
// Bumped by logout so a refresh that was already in flight cannot sign the user back in.
let sessionGeneration = 0
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

// Resolves the new token, null when the API rejects the session, or undefined on a transient failure.
async function fetchAccessToken(): Promise<string | null | undefined> {
  try {
    const { data, response } = await withRefreshLock(() =>
      sessionClient.POST('/api/v1/auth/refresh', {
        params: { header: CSRF_HEADER },
        credentials: 'same-origin',
      }),
    )
    if (data) return data.access_token
    return response.status === 401 ? null : undefined
  } catch (error) {
    if (!(error instanceof TypeError)) throw error
    return undefined
  }
}

async function requestAccessToken(): Promise<boolean> {
  const startedAt = sessionGeneration
  const token = await fetchAccessToken()
  if (startedAt !== sessionGeneration) return false
  if (token !== undefined || accessToken === null) setAccessToken(token ?? null)
  return typeof token === 'string'
}

export function getPendingRefresh(): Promise<boolean> | null {
  return pendingRefresh
}

export function refreshSession(): Promise<boolean> {
  pendingRefresh ??= requestAccessToken().finally(() => {
    pendingRefresh = null
  })
  return pendingRefresh
}

export async function logout(): Promise<void> {
  sessionGeneration += 1
  try {
    await sessionClient.POST('/api/v1/auth/logout', {
      params: { header: CSRF_HEADER },
      credentials: 'same-origin',
    })
  } finally {
    setAccessToken(null)
  }
}
