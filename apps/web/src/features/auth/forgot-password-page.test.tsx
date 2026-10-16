import { act, fireEvent, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '@/test/render-app'
import { server } from '@/test/server'

const FORGOT_URL = '*/api/v1/auth/password/forgot'
const HEADING = 'Recuperá tu contraseña'
const GENERIC_ERROR = 'No pudimos enviar el email. Probá de nuevo en unos minutos.'

function problem(status: number, code: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: code, status, detail: code, code, errors: [], request_id: 'r1' },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}

const accepted = () => HttpResponse.json({ status: 'accepted' }, { status: 202 })

function answerForgot(respond: () => Response) {
  const bodies: unknown[] = []
  server.use(
    http.post(FORGOT_URL, async ({ request }) => {
      bodies.push(await request.json())
      return respond()
    }),
  )
  return bodies
}

function submitEmail(email = 'rami@example.com') {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.click(screen.getByRole('button', { name: 'Enviar enlace' }))
}

async function openForgot() {
  const rendered = await renderApp('/forgot-password')
  await screen.findByRole('heading', { name: HEADING })
  return rendered
}

describe('/forgot-password', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('sends the email and shows a neutral sent state that never reveals whether the account exists', async () => {
    const bodies = answerForgot(accepted)
    await openForgot()

    submitEmail()

    expect(await screen.findByRole('heading', { name: 'Revisá tu email' })).toBeInTheDocument()
    expect(screen.getByText(/Si hay una cuenta asociada a/)).toHaveTextContent('rami@example.com')
    expect(screen.getByText(/Esperá unos minutos antes de pedirlo de nuevo/)).toBeInTheDocument()
    expect(screen.queryByText(/no existe ninguna cuenta|no encontramos tu cuenta/i)).not.toBeInTheDocument()
    expect(bodies).toEqual([{ email: 'rami@example.com' }])
    expect(screen.getByRole('link', { name: 'Volver a ingresar' })).toHaveAttribute('href', '/login')
  })

  it('validates the email without calling the API', async () => {
    const bodies = answerForgot(accepted)
    await openForgot()

    submitEmail('rami@')

    expect(await screen.findByText('Ingresá un email válido.')).toBeInTheDocument()
    expect(bodies).toHaveLength(0)
  })

  it.each([
    ['rate limited', () => problem(429, 'RATE_LIMITED')],
    ['a busy service', () => problem(503, 'SERVICE_BUSY')],
    ['a validation error', () => problem(422, 'VALIDATION_ERROR')],
    ['a network failure', () => HttpResponse.error()],
  ])('shows one generic retryable error on %s', async (_, respond) => {
    const bodies = answerForgot(respond)
    await openForgot()

    submitEmail()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Enviar enlace' })).toBeEnabled()
    expect(screen.getByRole('heading', { name: HEADING })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveValue('rami@example.com')
    expect(bodies).toEqual([{ email: 'rami@example.com' }])
  })

  it('gives up on a request that never answers after the timeout', async () => {
    const attempts: Request[] = []
    server.use(
      http.post(FORGOT_URL, async ({ request }) => {
        attempts.push(request)
        await delay('infinite')
      }),
    )
    await openForgot()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

    submitEmail()
    await vi.waitFor(() => expect(attempts).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Enviando…' })).toBeDisabled()
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    vi.useRealTimers()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Enviar enlace' })).toBeEnabled()
  })
})
