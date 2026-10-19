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

  it('marks the session unavailable on a network failure during the boot refresh', async () => {
    server.use(http.post(REFRESH_URL, () => HttpResponse.error()))

    await expect(modules.session.refreshSession()).resolves.toBe(false)

    expect(modules.session.getAuthStatus()).toBe('unavailable')
  })

  it('moves an unavailable session back to loading while a retry runs', async () => {
    server.use(http.post(REFRESH_URL, () => new HttpResponse(null, { status: 503 })))
    await modules.session.refreshSession()
    issueTokens('retry-token')

    const retry = modules.session.refreshSession()

    expect(modules.session.getAuthStatus()).toBe('loading')
    await retry
    expect(modules.session.getAuthStatus()).toBe('authenticated')
  })

  it('marks the session unavailable on a server error during the boot refresh', async () => {
    server.use(http.post(REFRESH_URL, () => new HttpResponse(null, { status: 503 })))

    await expect(modules.session.refreshSession()).resolves.toBe(false)

    expect(modules.session.getAuthStatus()).toBe('unavailable')
  })
})

describe('refresh failures with a session in place', () => {
  beforeEach(async () => {
    issueTokens('held-token')
    await modules.session.refreshSession()
  })

  it.each([
    ['a server error', () => new HttpResponse(null, { status: 503 })],
    ['rate limiting', () => new HttpResponse(null, { status: 429 })],
    ['a network failure', () => HttpResponse.error()],
  ])('keep the token and the authenticated status on %s', async (_, respond) => {
    server.use(http.post(REFRESH_URL, respond))

    await expect(modules.session.refreshSession()).resolves.toBe(false)

    expect(modules.session.getAccessToken()).toBe('held-token')
    expect(modules.session.getAuthStatus()).toBe('authenticated')
  })

  it('clear the token when the refresh is rejected', async () => {
    server.use(http.post(REFRESH_URL, () => new HttpResponse(null, { status: 401 })))

    await expect(modules.session.refreshSession()).resolves.toBe(false)

    expect(modules.session.getAccessToken()).toBeNull()
    expect(modules.session.getAuthStatus()).toBe('anonymous')
  })

  it('return the original 401 and keep the session when the retry refresh fails transiently', async () => {
    const authorizations = profileAcceptingOnly('never-issued')
    server.use(http.post(REFRESH_URL, () => new HttpResponse(null, { status: 503 })))

    const { response } = await modules.apiClient.GET('/api/v1/auth/me')

    expect(response.status).toBe(401)
    expect(authorizations).toEqual(['Bearer held-token'])
    expect(modules.session.getAccessToken()).toBe('held-token')
    expect(modules.session.getAuthStatus()).toBe('authenticated')
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

describe('signing in with a password', () => {
  it('adopts the token and marks the session authenticated', () => {
    modules.session.signIn('login-token')

    expect(modules.session.getAccessToken()).toBe('login-token')
    expect(modules.session.getAuthStatus()).toBe('authenticated')
  })

  it('keeps the sign-in when a refresh that started earlier is rejected afterwards', async () => {
    server.use(
      http.post(REFRESH_URL, async () => {
        await delay(30)
        return new HttpResponse(null, { status: 401 })
      }),
    )
    const refresh = modules.session.refreshSession()

    modules.session.signIn('login-token')

    await expect(refresh).resolves.toBe(false)
    expect(modules.session.getAccessToken()).toBe('login-token')
    expect(modules.session.getAuthStatus()).toBe('authenticated')
  })

  it('reports a refresh overtaken by a sign-in as superseded, not rejected', async () => {
    issueTokens('late-token')
    const refresh = modules.session.refreshSessionOutcome()

    modules.session.signIn('login-token')

    await expect(refresh).resolves.toBe('superseded')
    expect(modules.session.getAccessToken()).toBe('login-token')
  })
})

describe('malformed or hung refreshes', () => {
  afterEach(() => {
    vi.useRealTimers()
    Reflect.deleteProperty(navigator, 'locks')
  })

  function answerRefreshWithHtml() {
    server.use(
      http.post(
        REFRESH_URL,
        () => new HttpResponse('<html>oops</html>', { status: 200, headers: { 'Content-Type': 'text/html' } }),
      ),
    )
  }

  it('resolve false instead of rejecting when the refresh answers 200 with a non-JSON body', async () => {
    answerRefreshWithHtml()

    await expect(modules.session.refreshSession()).resolves.toBe(false)

    expect(modules.session.getAuthStatus()).toBe('unavailable')
  })

  it('log only the error type when the refresh fails unexpectedly', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    answerRefreshWithHtml()

    await modules.session.refreshSession()

    expect(consoleError).toHaveBeenCalledExactlyOnceWith('auth_refresh_failed', 'SyntaxError')
    consoleError.mockRestore()
  })

  it('return the original 401 when the retry refresh answers with a non-JSON body', async () => {
    issueTokens('held-token')
    await modules.session.refreshSession()
    profileAcceptingOnly('never-issued')
    answerRefreshWithHtml()

    const { response } = await modules.apiClient.GET('/api/v1/auth/me')

    expect(response.status).toBe(401)
    expect(modules.session.getAccessToken()).toBe('held-token')
  })

  it('give up on a refresh that never answers after the timeout', async () => {
    server.use(http.post(REFRESH_URL, () => delay('infinite')))
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

    const refresh = modules.session.refreshSession()
    await vi.advanceTimersByTimeAsync(10_000)

    await expect(refresh).resolves.toBe(false)
    expect(modules.session.getAuthStatus()).toBe('unavailable')
  })

  it('send a request with the current token once a refresh stuck behind another tab exceeds the wait bound', async () => {
    issueTokens('held-token')
    await modules.session.refreshSession()
    const authorizations = profileAcceptingOnly('held-token')
    // A lock that is never granted keeps the refresh pending without starting its own abort timer.
    Object.defineProperty(navigator, 'locks', { value: { request: () => new Promise(() => undefined) }, configurable: true })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    void modules.session.refreshSession()

    const request = modules.apiClient.GET('/api/v1/auth/me')
    await vi.advanceTimersByTimeAsync(10_000)
    const { response } = await request

    expect(response.status).toBe(200)
    expect(authorizations).toEqual(['Bearer held-token'])
  })
})

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

  it('ignore a refresh that completes after logout started', async () => {
    issueTokens('token')
    await modules.session.refreshSession()
    server.use(
      http.post(REFRESH_URL, async () => {
        await delay(50)
        return tokenResponse('late-token')
      }),
      http.post(LOGOUT_URL, () => new HttpResponse(null, { status: 204 })),
    )

    const refresh = modules.session.refreshSession()
    await modules.session.logout()

    await expect(refresh).resolves.toBe(false)
    expect(modules.session.getAccessToken()).toBeNull()
    expect(modules.session.getAuthStatus()).toBe('anonymous')
  })

  it('clears the pending refresh on logout', async () => {
    issueTokens('token')
    await modules.session.refreshSession()
    server.use(
      http.post(REFRESH_URL, async () => {
        await delay(50)
        return tokenResponse('late-token')
      }),
      http.post(LOGOUT_URL, () => new HttpResponse(null, { status: 204 })),
    )

    void modules.session.refreshSession()
    expect(modules.session.getPendingRefresh()).not.toBeNull()
    await modules.session.logout()

    expect(modules.session.getPendingRefresh()).toBeNull()
  })

  it('keeps a newer pending refresh when a refresh left behind by logout settles', async () => {
    const releases: (() => void)[] = []
    server.use(
      http.post(REFRESH_URL, async () => {
        await new Promise<void>((resolve) => releases.push(resolve))
        return tokenResponse('token')
      }),
      http.post(LOGOUT_URL, () => new HttpResponse(null, { status: 204 })),
    )

    const staleRefresh = modules.session.refreshSessionOutcome()
    await vi.waitFor(() => expect(releases).toHaveLength(1))
    await modules.session.logout()
    const newerRefresh = modules.session.refreshSessionOutcome()
    await vi.waitFor(() => expect(releases).toHaveLength(2))
    releases[0]?.()
    await staleRefresh

    expect(modules.session.getPendingRefresh()).toBe(newerRefresh)
    releases[1]?.()
    await newerRefresh
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

  it('wait for the pending boot refresh and send the request once with its token', async () => {
    const refreshes = issueTokens('boot-token')
    const authorizations = profileAcceptingOnly('boot-token')

    const boot = modules.session.refreshSession()
    const { response } = await modules.apiClient.GET('/api/v1/auth/me')
    await boot

    expect(response.status).toBe(200)
    expect(refreshes).toHaveLength(1)
    expect(authorizations).toEqual(['Bearer boot-token'])
  })

  it('send no authorization header to another origin', async () => {
    issueTokens('token-a')
    await modules.session.refreshSession()
    const authorizations = profileAcceptingOnly('token-a')

    const { response } = await modules.apiClient.GET('/api/v1/auth/me', {
      baseUrl: 'https://elsewhere.example',
    })

    expect(response.status).toBe(401)
    expect(authorizations).toEqual([null])
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

  it('retry with the newer token without refreshing again when one arrived meanwhile', async () => {
    const refreshes = issueTokens('expired-token', 'fresh-token')
    await modules.session.refreshSession()
    const authorizations: (string | null)[] = []
    server.use(
      http.get(ME_URL, async ({ request }) => {
        const authorization = request.headers.get('Authorization')
        authorizations.push(authorization)
        if (authorization === 'Bearer fresh-token') return HttpResponse.json(PROFILE)
        await delay(60)
        return new HttpResponse(null, { status: 401 })
      }),
    )

    const pending = modules.apiClient.GET('/api/v1/auth/me')
    await delay(5)
    await modules.session.refreshSession()
    const { response } = await pending

    expect(response.status).toBe(200)
    expect(refreshes).toHaveLength(2)
    expect(authorizations).toEqual(['Bearer expired-token', 'Bearer fresh-token'])
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
