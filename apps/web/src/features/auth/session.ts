import createClient from 'openapi-fetch'
import type { paths } from '@/api/generated/schema'
import { REQUEST_TIMEOUT_MS, withTimeout } from '@/features/auth/request-timeout'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'unavailable'

const CSRF_HEADER = { 'x-requested-with': 'investment-tracker' }
const REFRESH_LOCK = 'it-refresh'
// Bounds a hung refresh so it cannot hold the cross-tab lock, or block waiting requests, forever.
export const REFRESH_TIMEOUT_MS = REQUEST_TIMEOUT_MS

// Separate client without the auth middleware, so a failing refresh can never trigger another refresh.
const sessionClient = createClient<paths>({ baseUrl: window.location.origin })

let accessToken: string | null = null
let status: AuthStatus = 'loading'
let pendingRefresh: Promise<RefreshOutcome> | null = null
// Bumped by sign-in and logout so a refresh already in flight cannot overwrite the session that followed it.
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

function setStatus(nextStatus: AuthStatus) {
  if (nextStatus === status) return
  status = nextStatus
  listeners.forEach((listener) => listener())
}

function setAccessToken(token: string | null) {
  accessToken = token
  setStatus(token === null ? 'anonymous' : 'authenticated')
}

// Tabs refreshing at once would present the same it_rt; the API treats the second as reuse and revokes the family.
function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  if (!('locks' in navigator)) return task()
  return navigator.locks.request(REFRESH_LOCK, task)
}

// Resolves the new token, null when the API rejects the session, or undefined on a transient failure.
function postRefresh() {
  return withTimeout(
    (signal) =>
      sessionClient.POST('/api/v1/auth/refresh', {
        params: { header: CSRF_HEADER },
        credentials: 'same-origin',
        signal,
      }),
    REFRESH_TIMEOUT_MS,
  )
}

async function fetchAccessToken(): Promise<string | null | undefined> {
  try {
    const { data, response } = await withRefreshLock(postRefresh)
    if (data) return data.access_token
    return response.status === 401 ? null : undefined
  } catch (error) {
    // Network errors, timeouts and unparseable bodies are all transient: none proves the session is gone.
    // Only the type is logged: a message could carry the response body, token included.
    console.error('auth_refresh_failed', error instanceof Error ? error.name : typeof error)
    return undefined
  }
}

export type RefreshOutcome = 'refreshed' | 'rejected' | 'unavailable' | 'superseded'

async function requestAccessToken(): Promise<RefreshOutcome> {
  const startedAt = sessionGeneration
  const token = await fetchAccessToken()
  if (startedAt !== sessionGeneration) return 'superseded'
  if (token !== undefined) setAccessToken(token)
  // Without a held token a transient failure proves nothing either way, so the user is not sent to log in.
  else if (status === 'loading') setStatus('unavailable')
  if (token === undefined) return 'unavailable'
  return token === null ? 'rejected' : 'refreshed'
}

export function getPendingRefresh(): Promise<RefreshOutcome> | null {
  return pendingRefresh
}

export function refreshSessionOutcome(): Promise<RefreshOutcome> {
  if (pendingRefresh === null && status === 'unavailable') setStatus('loading')
  if (pendingRefresh !== null) return pendingRefresh
  const refresh = requestAccessToken().finally(() => {
    // Logout may already have handed the slot to a newer refresh.
    if (pendingRefresh === refresh) pendingRefresh = null
  })
  pendingRefresh = refresh
  return refresh
}

export async function refreshSession(): Promise<boolean> {
  return (await refreshSessionOutcome()) === 'refreshed'
}

export function signIn(token: string): void {
  sessionGeneration += 1
  setAccessToken(token)
}

export async function logout(): Promise<void> {
  sessionGeneration += 1
  // The pending refresh belongs to the session being left; callers must not await its stale outcome.
  pendingRefresh = null
  try {
    await sessionClient.POST('/api/v1/auth/logout', {
      params: { header: CSRF_HEADER },
      credentials: 'same-origin',
    })
  } finally {
    setAccessToken(null)
  }
}
