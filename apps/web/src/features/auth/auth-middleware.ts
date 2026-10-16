import type { Middleware } from 'openapi-fetch'
import { getAccessToken, getPendingRefresh, refreshSession } from '@/features/auth/session'

// Untouched copies of bearer requests: the original body is consumed by the first attempt.
const retryableRequests = new WeakMap<Request, Request>()

export const authMiddleware: Middleware = {
  async onRequest({ request }) {
    if (new URL(request.url).origin !== window.location.origin) return undefined
    // A request sent mid-refresh (e.g. during the boot refresh) would go out without the token about to arrive.
    await getPendingRefresh()?.catch(() => false)
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
    if (!(await refreshSession())) return undefined
    retry.headers.set('Authorization', `Bearer ${getAccessToken()}`)
    return options.fetch(retry)
  },
}
