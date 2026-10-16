import { act, fireEvent, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '@/test/render-app'
import { server } from '@/test/server'

const RESET_URL = '*/api/v1/auth/password/reset'
const TOKEN = 'secret-reset-token'
const HEADING = 'Creá tu nueva contraseña'
const GENERIC_ERROR = 'No pudimos guardar la contraseña. Probá de nuevo en unos minutos.'

function problem(status: number, code: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: code, status, detail: code, code, errors: [], request_id: 'r1' },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}

const saved = () => new HttpResponse(null, { status: 204 })

function answerReset(...responders: (() => Response)[]) {
  const bodies: unknown[] = []
  server.use(
    http.post(RESET_URL, async ({ request }) => {
      bodies.push(await request.json())
      const respond = responders[Math.min(bodies.length, responders.length) - 1] ?? saved
      return respond()
    }),
  )
  return bodies
}

function submitPassword(password = 'correct horse battery') {
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Guardar contraseña' }))
}

async function openResetLink() {
  const rendered = await renderApp(`/reset-password#token=${TOKEN}`)
  await screen.findByRole('heading', { name: HEADING })
  return rendered
}

describe('/reset-password', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('clears the token from the URL before any request and never renders it', async () => {
    const bodies = answerReset(saved)
    const { router } = await openResetLink()

    expect(router.state.location.hash).toBe('')
    expect(router.state.location.pathname).toBe('/reset-password')
    expect(document.body).not.toHaveTextContent(TOKEN)
    expect(bodies).toHaveLength(0)
  })

  it('validates the password length without calling the API', async () => {
    const bodies = answerReset(saved)
    await openResetLink()

    submitPassword('short')

    expect(await screen.findByText('Usá al menos 12 caracteres.')).toBeInTheDocument()
    expect(screen.getByText('5 / 12')).toBeInTheDocument()
    expect(bodies).toHaveLength(0)
  })

  it('sends the token with the new password and lands on login with an updated-password notice', async () => {
    const bodies = answerReset(saved)
    const { router } = await openResetLink()

    submitPassword()

    expect(await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Tu contraseña fue actualizada. Ingresá con la nueva.')
    expect(bodies).toEqual([{ token: TOKEN, password: 'correct horse battery' }])
    expect(router.state.location.pathname).toBe('/login')
  })

  it('shows a generic invalid-link state with a way to request a new link on a 400', async () => {
    answerReset(() => problem(400, 'INVALID_EMAIL_TOKEN'))
    await openResetLink()

    submitPassword()

    expect(await screen.findByRole('heading', { name: 'Este enlace no es válido' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Contraseña')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Pedir un enlace nuevo' })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
    expect(screen.getByRole('link', { name: 'Volver a ingresar' })).toHaveAttribute('href', '/login')
    expect(document.body).not.toHaveTextContent(TOKEN)
  })

  it('offers only the invalid state when the URL carries no token', async () => {
    const bodies = answerReset(saved)
    await renderApp('/reset-password')

    expect(await screen.findByRole('heading', { name: 'Este enlace no es válido' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Contraseña')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Pedir un enlace nuevo' })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
    expect(bodies).toHaveLength(0)
  })

  it.each([
    ['a rate limit', () => problem(429, 'RATE_LIMITED')],
    ['a busy service', () => problem(503, 'SERVICE_BUSY')],
    ['a validation error', () => problem(422, 'VALIDATION_ERROR')],
    ['a network failure', () => HttpResponse.error()],
  ])('shows a retryable error on %s', async (_, respond) => {
    const bodies = answerReset(respond)
    await openResetLink()

    submitPassword()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Guardar contraseña' })).toBeEnabled()
    expect(screen.getByRole('heading', { name: HEADING })).toBeInTheDocument()
    expect(bodies).toEqual([{ token: TOKEN, password: 'correct horse battery' }])
  })

  it('gives up on a reset that never answers after the timeout', async () => {
    const attempts: Request[] = []
    server.use(
      http.post(RESET_URL, async ({ request }) => {
        attempts.push(request)
        await delay('infinite')
      }),
    )
    await openResetLink()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

    submitPassword()
    await vi.waitFor(() => expect(attempts).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Guardando…' })).toBeDisabled()
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    vi.useRealTimers()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Guardar contraseña' })).toBeEnabled()
  })
})
