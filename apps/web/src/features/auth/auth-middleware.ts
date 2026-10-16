import type { Middleware } from 'openapi-fetch'
import {
  getAccessToken,
  getPendingRefresh,
  REFRESH_TIMEOUT_MS,
  refreshSession,
} from '@/features/auth/session'

// Untouched copies of bearer requests: the original body is consumed by the first attempt.
const retryableRequests = new WeakMap<Request, Request>()

async function waitForPendingRefresh(): Promise<void> {
  const pending = getPendingRefresh()
  if (pending === null) return
  let timer: ReturnType<typeof setTimeout> | undefined
  const bound = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, REFRESH_TIMEOUT_MS)
  })
  await Promise.race([pending.catch(() => false), bound])
  clearTimeout(timer)
}

export const authMiddleware: Middleware = {
  async onRequest({ request }) {
    if (new URL(request.url).origin !== window.location.origin) return undefined
    // A request sent mid-refresh (e.g. during the boot refresh) would go out without the token about to arrive.
    await waitForPendingRefresh()
    const token = getAccessToken()
    if (token === null) return undefined
    request.headers.set('Authorization', `Bearer ${token}`)
    retryableRequests.set(request, request.clone())
    return request
  },
  async onResponse({ request, response, options }) {
    const retry = retryableRequests.get(request)
    retryableRequests.delete(request)
    if (response.status !== 401 || retry === undefined) return undefined
    const current = getAccessToken()
    const hasNewerToken = current !== null && retry.headers.get('Authorization') !== `Bearer ${current}`
    if (!hasNewerToken && !(await refreshSession())) return undefined
    retry.headers.set('Authorization', `Bearer ${getAccessToken()}`)
    return options.fetch(retry)
  },
}
