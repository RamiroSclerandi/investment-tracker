import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '@/test/render-app'
import { server } from '@/test/server'

const LOGIN_URL = '*/api/v1/auth/login'
const RESEND_URL = '*/api/v1/auth/resend-verification'
const REFRESH_URL = '*/api/v1/auth/refresh'

function problem(status: number, code: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: code, status, detail: code, code, errors: [], request_id: 'r1' },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}

function answerLogin(respond: () => Response) {
  const bodies: unknown[] = []
  server.use(
    http.post(LOGIN_URL, async ({ request }) => {
      bodies.push(await request.json())
      return respond()
    }),
  )
  return bodies
}

function fillAndSubmit(email = 'ana@example.com', password = 'correct horse battery') {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))
}

describe('/login', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('offers Google sign-in, registration and password recovery', async () => {
    await renderApp('/login')

    expect(await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continuar con Google' })).toHaveAttribute(
      'href',
      '/api/v1/auth/google/start',
    )
    expect(screen.getByRole('link', { name: 'Creá una' })).toHaveAttribute('href', '/register')
    expect(screen.getByRole('link', { name: '¿La olvidaste?' })).toHaveAttribute('href', '/forgot-password')
    expect(screen.queryByText('Tu email está verificado. Ya podés ingresar.')).not.toBeInTheDocument()
  })

  it('validates the fields without calling the API', async () => {
    const bodies = answerLogin(() => problem(401, 'INVALID_CREDENTIALS'))
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit('ana@', '')

    expect(await screen.findByText('Ingresá un email válido.')).toBeInTheDocument()
    expect(screen.getByText('Ingresá tu contraseña.')).toBeInTheDocument()
    expect(bodies).toHaveLength(0)
  })

  it('adopts the access token and lands on the dashboard', async () => {
    const bodies = answerLogin(() =>
      HttpResponse.json({ access_token: 'login-token', expires_in: 900, token_type: 'Bearer' }),
    )
    const { router, session } = await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit()

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(bodies).toEqual([{ email: 'ana@example.com', password: 'correct horse battery' }])
    expect(session.getAccessToken()).toBe('login-token')
    expect(session.getAuthStatus()).toBe('authenticated')
    expect(router.state.location.pathname).toBe('/')
  })

  it('shows a generic error and clears the password on invalid credentials', async () => {
    answerLogin(() => problem(401, 'INVALID_CREDENTIALS'))
    const { session } = await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit()

    expect(await screen.findByRole('alert')).toHaveTextContent('Email o contraseña incorrectos.')
    expect(screen.getByLabelText('Contraseña')).toHaveValue('')
    expect(screen.getByLabelText('Email')).toHaveValue('ana@example.com')
    expect(session.getAccessToken()).toBeNull()
  })

  it('tells the user to wait when rate limited', async () => {
    answerLogin(() => problem(429, 'RATE_LIMITED'))
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Demasiados intentos. Probá de nuevo en 1 minuto.',
    )
  })

  it.each([
    ['a busy service', () => problem(503, 'SERVICE_BUSY')],
    ['a validation error', () => problem(422, 'VALIDATION_ERROR')],
    ['an unexpected 403', () => problem(403, 'FORBIDDEN')],
    ['a network failure', () => HttpResponse.error()],
  ])('shows a retryable error on %s', async (_, respond) => {
    answerLogin(respond)
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No pudimos ingresar. Probá de nuevo en unos minutos.',
    )
    expect(screen.getByRole('button', { name: 'Ingresar' })).toBeEnabled()
  })

  it('gives up on a login that never answers after the timeout', async () => {
    const attempts: Request[] = []
    server.use(
      http.post(LOGIN_URL, async ({ request }) => {
        attempts.push(request)
        await delay('infinite')
      }),
    )
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

    fillAndSubmit()
    await vi.waitFor(() => expect(attempts).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Ingresando…' })).toBeDisabled()
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    vi.useRealTimers()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No pudimos ingresar. Probá de nuevo en unos minutos.',
    )
    expect(screen.getByRole('button', { name: 'Ingresar' })).toBeEnabled()
  })

  it('offers to resend the verification email to the typed address when unverified', async () => {
    answerLogin(() => problem(403, 'EMAIL_NOT_VERIFIED'))
    const resends: unknown[] = []
    server.use(
      http.post(RESEND_URL, async ({ request }) => {
        resends.push(await request.json())
        return HttpResponse.json({ status: 'accepted' }, { status: 202 })
      }),
    )
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit('rami@example.com')
    expect(await screen.findByText('Verificá tu email para continuar')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reenviar email de verificación' }))

    expect(
      await screen.findByText('Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.'),
    ).toBeInTheDocument()
    expect(resends).toEqual([{ email: 'rami@example.com' }])
  })

  function answerResends(...statuses: (202 | 429 | 503)[]) {
    const bodies: unknown[] = []
    server.use(
      http.post(RESEND_URL, async ({ request }) => {
        bodies.push(await request.json())
        const status = statuses[Math.min(bodies.length, statuses.length) - 1] ?? 202
        if (status === 202) return HttpResponse.json({ status: 'accepted' }, { status })
        return problem(status, status === 429 ? 'RATE_LIMITED' : 'SERVICE_BUSY')
      }),
    )
    return bodies
  }

  it('resends to the submitted address even after the email field changes', async () => {
    answerLogin(() => problem(403, 'EMAIL_NOT_VERIFIED'))
    const resends = answerResends(202)
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit('rami@example.com')
    await screen.findByText('Verificá tu email para continuar')
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'otra@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reenviar email de verificación' }))

    expect(await screen.findByRole('button', { name: 'Reenviar en 1:00' })).toBeDisabled()
    expect(resends).toEqual([{ email: 'rami@example.com' }])
  })

  it('keeps the resend button available for a retry after a failed resend', async () => {
    answerLogin(() => problem(403, 'EMAIL_NOT_VERIFIED'))
    const resends = answerResends(503, 202)
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })

    fillAndSubmit('rami@example.com')
    fireEvent.click(await screen.findByRole('button', { name: 'Reenviar email de verificación' }))
    expect(
      await screen.findByText('No pudimos reenviar el email. Probá de nuevo en unos minutos.'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reenviar email de verificación' }))

    expect(
      await screen.findByText('Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.'),
    ).toBeInTheDocument()
    expect(resends).toEqual([{ email: 'rami@example.com' }, { email: 'rami@example.com' }])
  })

  it('lets the user resend again once the cooldown after a rate limit ends', async () => {
    answerLogin(() => problem(403, 'EMAIL_NOT_VERIFIED'))
    const resends = answerResends(429, 202)
    await renderApp('/login')
    await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })
    fillAndSubmit('rami@example.com')
    const resendButton = await screen.findByRole('button', { name: 'Reenviar email de verificación' })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

    fireEvent.click(resendButton)
    await vi.waitFor(() =>
      expect(screen.getByText('Demasiados intentos. Probá de nuevo en 1 minuto.')).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Reenviar en 1:00' })).toBeDisabled()
    for (let second = 0; second < 60; second += 1) {
      await act(() => vi.advanceTimersByTimeAsync(1_000))
    }
    vi.useRealTimers()
    fireEvent.click(screen.getByRole('button', { name: 'Reenviar email de verificación' }))

    await waitFor(() => expect(resends).toHaveLength(2))
  })

  it('redirects to the dashboard when a session already exists', async () => {
    server.use(
      http.post(REFRESH_URL, () =>
        HttpResponse.json({ access_token: 'held', expires_in: 900, token_type: 'Bearer' }),
      ),
    )
    const { router, session } = await renderApp('/login')

    await session.refreshSession()

    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })
})
