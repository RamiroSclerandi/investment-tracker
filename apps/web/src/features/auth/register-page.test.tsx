import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '@/test/render-app'
import { server } from '@/test/server'

const REGISTER_URL = '*/api/v1/auth/register'
const RESEND_URL = '*/api/v1/auth/resend-verification'
const REFRESH_URL = '*/api/v1/auth/refresh'
const HEADING = 'Creá tu cuenta'
const GENERIC_ERROR = 'No pudimos crear la cuenta. Probá de nuevo en unos minutos.'

function problem(status: number, code: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: code, status, detail: code, code, errors: [], request_id: 'r1' },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}

function answerRegister(respond: () => Response) {
  const bodies: unknown[] = []
  server.use(
    http.post(REGISTER_URL, async ({ request }) => {
      bodies.push(await request.json())
      return respond()
    }),
  )
  return bodies
}

const accepted = () => HttpResponse.json({ status: 'accepted' }, { status: 202 })

function fillAndSubmit({ name = '  Rami  ', email = 'rami@example.com', password = 'correct horse battery' } = {}) {
  fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: name } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Crear cuenta' }))
}

async function openRegister() {
  const rendered = await renderApp('/register')
  await screen.findByRole('heading', { name: HEADING })
  return rendered
}

describe('/register', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('offers Google sign-up and a way back to login', async () => {
    await openRegister()

    expect(screen.getByText('Vas a necesitar verificar tu email.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Registrarme con Google' })).toHaveAttribute(
      'href',
      '/api/v1/auth/google/start',
    )
    expect(screen.getByRole('link', { name: 'Ingresá' })).toHaveAttribute('href', '/login')
  })

  it('validates empty and short fields without calling the API', async () => {
    const bodies = answerRegister(accepted)
    await openRegister()

    fillAndSubmit({ name: '   ', email: 'rami@', password: 'short pass' })

    expect(await screen.findByText('Ingresá tu nombre.')).toBeInTheDocument()
    expect(screen.getByText('Ingresá un email válido.')).toBeInTheDocument()
    expect(screen.getByText('Usá al menos 12 caracteres.')).toBeInTheDocument()
    expect(screen.getByText('10 / 12')).toBeInTheDocument()
    expect(screen.getByLabelText('Contraseña')).toHaveAttribute('aria-invalid', 'true')
    expect(bodies).toHaveLength(0)
  })

  it('validates names and passwords over the maximum length', async () => {
    const bodies = answerRegister(accepted)
    await openRegister()

    fillAndSubmit({ name: 'a'.repeat(81), password: 'p'.repeat(129) })

    expect(await screen.findByText('Usá hasta 80 caracteres.')).toBeInTheDocument()
    expect(screen.getByText('Usá hasta 128 caracteres.')).toBeInTheDocument()
    expect(bodies).toHaveLength(0)
  })

  it('sends the trimmed name and shows a neutral check-your-email state', async () => {
    const bodies = answerRegister(accepted)
    const { session } = await openRegister()

    fillAndSubmit()

    expect(await screen.findByRole('heading', { name: 'Revisá tu email' })).toBeInTheDocument()
    expect(
      screen.getByText(/Si el registro puede completarse, vas a recibir un enlace en/),
    ).toHaveTextContent('rami@example.com')
    expect(bodies).toEqual([
      { display_name: 'Rami', email: 'rami@example.com', password: 'correct horse battery' },
    ])
    expect(screen.getByRole('button', { name: 'Reenviar en 1:00' })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Volver a ingresar' })).toHaveAttribute('href', '/login')
    expect(session.getAccessToken()).toBeNull()
  })

  it('resends to the submitted address once the cooldown ends', async () => {
    answerRegister(accepted)
    const resends: unknown[] = []
    server.use(
      http.post(RESEND_URL, async ({ request }) => {
        resends.push(await request.json())
        return accepted()
      }),
    )
    await openRegister()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    fillAndSubmit()
    await vi.waitFor(() => expect(screen.getByRole('heading', { name: 'Revisá tu email' })).toBeInTheDocument())

    for (let second = 0; second < 60; second += 1) {
      await act(() => vi.advanceTimersByTimeAsync(1_000))
    }
    vi.useRealTimers()
    fireEvent.click(screen.getByRole('button', { name: 'Reenviar email' }))

    expect(
      await screen.findByText('Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.'),
    ).toBeInTheDocument()
    expect(resends).toEqual([{ email: 'rami@example.com' }])
  })

  it('tells the user to wait when rate limited', async () => {
    answerRegister(() => problem(429, 'RATE_LIMITED'))
    await openRegister()

    fillAndSubmit()

    expect(await screen.findByRole('alert')).toHaveTextContent('Demasiados intentos. Probá de nuevo en 1 minuto.')
    expect(screen.getByRole('heading', { name: HEADING })).toBeInTheDocument()
  })

  it.each([
    ['a busy service', () => problem(503, 'SERVICE_BUSY')],
    ['a validation error', () => problem(422, 'VALIDATION_ERROR')],
    ['a network failure', () => HttpResponse.error()],
  ])('shows a retryable error on %s', async (_, respond) => {
    answerRegister(respond)
    await openRegister()

    fillAndSubmit()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Crear cuenta' })).toBeEnabled()
    expect(screen.getByLabelText('Email')).toHaveValue('rami@example.com')
  })

  it('gives up on a registration that never answers after the timeout', async () => {
    const attempts: Request[] = []
    server.use(
      http.post(REGISTER_URL, async ({ request }) => {
        attempts.push(request)
        await delay('infinite')
      }),
    )
    await openRegister()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

    fillAndSubmit()
    await vi.waitFor(() => expect(attempts).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Creando cuenta…' })).toBeDisabled()
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    vi.useRealTimers()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Crear cuenta' })).toBeEnabled()
  })

  it('redirects to the dashboard when a session already exists', async () => {
    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ access_token: 'held', expires_in: 900, token_type: 'Bearer' })),
    )
    const { router, session } = await openRegister()

    await session.refreshSession()

    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })
})
