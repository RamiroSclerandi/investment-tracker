import { act, renderHook, waitFor } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '@/test/server'

const REFRESH_URL = '*/api/v1/auth/refresh'
const LOGOUT_URL = '*/api/v1/auth/logout'
const ME_URL = '*/api/v1/auth/me'
const PROFILE = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'ana@example.com',
  display_name: 'Ana',
  email_verified: true,
  preferred_currency: 'ARS',
  has_password: true,
}

type Modules = {
  session: typeof import('@/features/auth/session')
  useAuthStatus: typeof import('@/features/auth/use-auth-status').useAuthStatus
  apiClient: typeof import('@/api/client').apiClient
}

let modules: Modules

function tokenResponse(token: string) {
  return HttpResponse.json({ access_token: token, expires_in: 900, token_type: 'Bearer' })
}

function issueTokens(...tokens: string[]) {
  const seen: Request[] = []
  server.use(
    http.post(REFRESH_URL, async ({ request }) => {
      seen.push(request)
      await delay(20)
      return tokenResponse(tokens[Math.min(seen.length, tokens.length) - 1] ?? '')
    }),
  )
  return seen
}

function profileAcceptingOnly(token: string) {
  const seen: (string | null)[] = []
  server.use(
    http.get(ME_URL, ({ request }) => {
      const authorization = request.headers.get('Authorization')
      seen.push(authorization)
      if (authorization !== `Bearer ${token}`) return new HttpResponse(null, { status: 401 })
      return HttpResponse.json(PROFILE)
    }),
  )
  return seen
}

beforeEach(async () => {
  vi.resetModules()
  modules = {
    session: await import('@/features/auth/session'),
    useAuthStatus: (await import('@/features/auth/use-auth-status')).useAuthStatus,
    apiClient: (await import('@/api/client')).apiClient,
  }
  localStorage.clear()
  sessionStorage.clear()
})

describe('silent refresh on boot', () => {
  it('moves the status from loading to authenticated when the refresh succeeds', async () => {
    issueTokens('boot-token')
    const { result } = renderHook(() => modules.useAuthStatus())
    expect(result.current).toBe('loading')

    await act(() => modules.session.refreshSession())

    expect(result.current).toBe('authenticated')
    expect(modules.session.getAccessToken()).toBe('boot-token')
  })

  it('moves the status from loading to anonymous when the refresh is rejected', async () => {
    server.use(http.post(REFRESH_URL, () => new HttpResponse(null, { status: 401 })))
    const { result } = renderHook(() => modules.useAuthStatus())
    expect(result.current).toBe('loading')

    await act(() => modules.session.refreshSession())

    expect(result.current).toBe('anonymous')
    expect(modules.session.getAccessToken()).toBeNull()
  })

  it('treats a network failure during refresh as signed out', async () => {
    server.use(http.post(REFRESH_URL, () => HttpResponse.error()))

    await expect(modules.session.refreshSession()).resolves.toBe(false)

    expect(modules.session.getAuthStatus()).toBe('anonymous')
  })
})

function installFakeLocks() {
  const names: string[] = []
  let tail: Promise<unknown> = Promise.resolve()
  const locks = {
    request: (name: string, callback: () => Promise<unknown>) => {
      names.push(name)
      const run = tail.then(() => callback())
      tail = run.catch(() => undefined)
      return run
    },
  }
  Object.defineProperty(navigator, 'locks', { value: locks, configurable: true })
  return names
}

describe('refresh across tabs', () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'locks')
  })

  it('never has two refresh requests in flight when two tabs refresh at once', async () => {
    const lockNames = installFakeLocks()
    let inFlight = 0
    let maxInFlight = 0
    let issued = 0
    server.use(
      http.post(REFRESH_URL, async () => {
        inFlight += 1
        maxInFlight = Math.max(maxInFlight, inFlight)
        await delay(20)
        inFlight -= 1
        issued += 1
        return tokenResponse(`token-${issued}`)
      }),
    )
    const firstTab = modules.session
    vi.resetModules()
    const secondTab = await import('@/features/auth/session')

    const outcomes = await Promise.all([firstTab.refreshSession(), secondTab.refreshSession()])

    expect(outcomes).toEqual([true, true])
    expect(issued).toBe(2)
    expect(maxInFlight).toBe(1)
    expect(lockNames).toEqual(['it-refresh', 'it-refresh'])
    expect(new Set([firstTab.getAccessToken(), secondTab.getAccessToken()])).toEqual(
      new Set(['token-1', 'token-2']),
    )
  })
})

describe('refresh and logout requests', () => {
  it('send the CSRF header on refresh', async () => {
    const refreshes = issueTokens('token')

    await modules.session.refreshSession()

    expect(refreshes[0]?.headers.get('X-Requested-With')).toBe('investment-tracker')
  })

  it('send the CSRF header on logout and clear the token even when logout fails', async () => {
    issueTokens('token')
    await modules.session.refreshSession()
    const logouts: Request[] = []
    server.use(
      http.post(LOGOUT_URL, ({ request }) => {
        logouts.push(request)
        return new HttpResponse(null, { status: 500 })
      }),
    )

    await modules.session.logout()

    expect(logouts).toHaveLength(1)
    expect(logouts[0]?.headers.get('X-Requested-With')).toBe('investment-tracker')
    expect(modules.session.getAccessToken()).toBeNull()
    expect(modules.session.getAuthStatus()).toBe('anonymous')
  })

  it('keeps the access token out of web storage and cookies', async () => {
    issueTokens('secret-access-token')

    await modules.session.refreshSession()

    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(document.cookie).not.toContain('secret-access-token')
  })
})

describe('authenticated API requests', () => {
  it('add the bearer token when one is held', async () => {
    issueTokens('token-a')
    await modules.session.refreshSession()
    const authorizations = profileAcceptingOnly('token-a')

    const { response } = await modules.apiClient.GET('/api/v1/auth/me')

    expect(response.status).toBe(200)
    expect(authorizations).toEqual(['Bearer token-a'])
  })

  it('send no authorization header while signed out', async () => {
    const authorizations = profileAcceptingOnly('token-a')

    const { response } = await modules.apiClient.GET('/api/v1/auth/me')

    expect(response.status).toBe(401)
    expect(authorizations).toEqual([null])
  })

  it('share one refresh between concurrent 401s and retry each request with the new token', async () => {
    const refreshes = issueTokens('expired-token', 'fresh-token')
    await modules.session.refreshSession()
    const authorizations = profileAcceptingOnly('fresh-token')

    const [first, second] = await Promise.all([
      modules.apiClient.GET('/api/v1/auth/me'),
      modules.apiClient.GET('/api/v1/auth/me'),
    ])

    expect(refreshes).toHaveLength(2)
    expect(first.response.status).toBe(200)
    expect(second.response.status).toBe(200)
    expect(first.data).toEqual(PROFILE)
    expect(second.data).toEqual(PROFILE)
    expect(authorizations).toEqual([
      'Bearer expired-token',
      'Bearer expired-token',
      'Bearer fresh-token',
      'Bearer fresh-token',
    ])
  })

  it('clear the session and return the 401 without retrying when the refresh fails', async () => {
    issueTokens('expired-token')
    await modules.session.refreshSession()
    const authorizations = profileAcceptingOnly('never-issued')
    let refreshCalls = 0
    server.use(
      http.post(REFRESH_URL, () => {
        refreshCalls += 1
        return new HttpResponse(null, { status: 401 })
      }),
    )

    const { response } = await modules.apiClient.GET('/api/v1/auth/me')

    expect(response.status).toBe(401)
    expect(refreshCalls).toBe(1)
    expect(authorizations).toEqual(['Bearer expired-token'])
    expect(modules.session.getAccessToken()).toBeNull()
    await waitFor(() => expect(modules.session.getAuthStatus()).toBe('anonymous'))
  })

  it('retry a request with a body after refreshing', async () => {
    issueTokens('expired-token', 'fresh-token')
    await modules.session.refreshSession()
    const bodies: unknown[] = []
    server.use(
      http.patch(ME_URL, async ({ request }) => {
        bodies.push(await request.json())
        if (request.headers.get('Authorization') !== 'Bearer fresh-token') {
          return new HttpResponse(null, { status: 401 })
        }
        return HttpResponse.json({ ...PROFILE, display_name: 'Ana B' })
      }),
    )

    const { response } = await modules.apiClient.PATCH('/api/v1/auth/me', {
      body: { display_name: 'Ana B' },
    })

    expect(response.status).toBe(200)
    expect(bodies).toEqual([{ display_name: 'Ana B' }, { display_name: 'Ana B' }])
  })
})
