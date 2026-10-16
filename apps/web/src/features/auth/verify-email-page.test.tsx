import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '@/test/render-app'
import { server } from '@/test/server'

const VERIFY_URL = '*/api/v1/auth/verify-email'
const RESEND_URL = '*/api/v1/auth/resend-verification'
const TOKEN = 'aB-_9xY0zQ'
const HEADING = 'Verificá tu email'
const INVALID_MESSAGE = 'Enlace inválido o contraseña incorrecta.'
const GENERIC_ERROR = 'No pudimos verificar tu email. Probá de nuevo en unos minutos.'

function problem(status: number, code: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: code, status, detail: code, code, errors: [], request_id: 'r1' },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  )
}

const verified = () => HttpResponse.json({ status: 'verified' })

function answerVerify(...responders: (() => Response)[]) {
  const bodies: unknown[] = []
  server.use(
    http.post(VERIFY_URL, async ({ request }) => {
      bodies.push(await request.json())
      const respond = responders[Math.min(bodies.length, responders.length) - 1] ?? verified
      return respond()
    }),
  )
  return bodies
}

function answerResends() {
  const bodies: unknown[] = []
  server.use(
    http.post(RESEND_URL, async ({ request }) => {
      bodies.push(await request.json())
      return HttpResponse.json({ status: 'accepted' }, { status: 202 })
    }),
  )
  return bodies
}

function submitPassword(password = 'correct horse battery') {
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Verificar email' }))
}

async function openVerifyLink() {
  const rendered = await renderApp(`/verify-email#token=${TOKEN}`)
  await screen.findByRole('heading', { name: HEADING })
  return rendered
}

describe('/verify-email', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('clears the token from the URL before any request and never renders it', async () => {
    const bodies = answerVerify(verified)
    const { router } = await openVerifyLink()

    await waitFor(() => expect(router.state.location.hash).toBe(''))
    expect(router.state.location.pathname).toBe('/verify-email')
    expect(document.body).not.toHaveTextContent(TOKEN)
    expect(bodies).toHaveLength(0)
  })

  it('clears the token hash before the verify request leaves', async () => {
    const { router } = await openVerifyLink()
    const bodies: unknown[] = []
    let hashAtRequest: string | undefined
    server.use(
      http.post(VERIFY_URL, async ({ request }) => {
        hashAtRequest = router.state.location.hash
        bodies.push(await request.json())
        return verified()
      }),
    )
    await waitFor(() => expect(router.state.location.hash).toBe(''))

    submitPassword()

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(hashAtRequest).toBe('')
    expect(bodies[0]).toEqual({ token: TOKEN, password: 'correct horse battery' })
  })

  it('validates the password length without calling the API', async () => {
    const bodies = answerVerify(verified)
    await openVerifyLink()

    submitPassword('short')

    expect(await screen.findByText('Usá al menos 12 caracteres.')).toBeInTheDocument()
    expect(screen.getByText('5 / 12')).toBeInTheDocument()
    expect(bodies).toHaveLength(0)
  })

  it('sends the token with the password and lands on login with a verified notice', async () => {
    const bodies = answerVerify(verified)
    const { router } = await openVerifyLink()

    submitPassword()

    expect(await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Tu email está verificado. Ya podés ingresar.')
    expect(bodies).toEqual([{ token: TOKEN, password: 'correct horse battery' }])
    expect(router.state.location.pathname).toBe('/login')
  })

  it('shows one generic error on a bad token or wrong password and retries with the same token', async () => {
    const bodies = answerVerify(() => problem(400, 'INVALID_EMAIL_TOKEN'), verified)
    await openVerifyLink()

    submitPassword('wrong password!')

    expect(await screen.findByRole('alert')).toHaveTextContent(INVALID_MESSAGE)
    expect(screen.getByLabelText('Contraseña')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Enviar nuevo enlace' })).toBeEnabled()
    submitPassword()
    expect(await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })).toBeInTheDocument()
    expect(bodies).toEqual([
      { token: TOKEN, password: 'wrong password!' },
      { token: TOKEN, password: 'correct horse battery' },
    ])
  })

  it('resends a new link to the submitted address after an invalid link', async () => {
    answerVerify(() => problem(400, 'INVALID_EMAIL_TOKEN'))
    const resends = answerResends()
    await openVerifyLink()
    submitPassword()
    await screen.findByRole('alert')

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'rami@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar nuevo enlace' }))

    expect(
      await screen.findByText('Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reenviar en 1:00' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'otra@example.com' } })
    expect(resends).toEqual([{ email: 'rami@example.com' }])
  })

  it('keeps the resend cooldown when the resend form remounts', async () => {
    const bodies = answerVerify(
      () => problem(400, 'INVALID_EMAIL_TOKEN'),
      () => problem(400, 'INVALID_EMAIL_TOKEN'),
    )
    const resends = answerResends()
    await openVerifyLink()
    submitPassword('wrong password!')
    await screen.findByRole('alert')

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'rami@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar nuevo enlace' }))
    expect(
      await screen.findByText('Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.'),
    ).toBeInTheDocument()

    // A new verify submit unmounts the resend section; the wait must survive the remount.
    submitPassword('wrong password!')
    await waitFor(() => expect(bodies).toHaveLength(2))
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'rami@example.com' } })

    expect(screen.getByRole('button', { name: /Reenviar en/ })).toBeDisabled()
    expect(resends).toEqual([{ email: 'rami@example.com' }])
  })

  it('does not block a resend to a different address during a cooldown', async () => {
    answerVerify(() => problem(400, 'INVALID_EMAIL_TOKEN'))
    const resends = answerResends()
    await openVerifyLink()
    submitPassword()
    await screen.findByRole('alert')

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'rami@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar nuevo enlace' }))
    expect(
      await screen.findByText('Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.'),
    ).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'otra@example.com' } })

    expect(screen.getByRole('button', { name: 'Enviar nuevo enlace' })).toBeEnabled()
    expect(resends).toEqual([{ email: 'rami@example.com' }])
  })

  it('hints that an already verified account can log in when the link is invalid', async () => {
    answerVerify(() => problem(400, 'INVALID_EMAIL_TOKEN'))
    await openVerifyLink()

    submitPassword('wrong password!')

    expect(await screen.findByRole('alert')).toHaveTextContent(INVALID_MESSAGE)
    const loginHint = screen.getByRole('link', { name: 'podés iniciar sesión' })
    expect(loginHint).toHaveAttribute('href', '/login')
    expect(loginHint.parentElement).toHaveTextContent('Si ya verificaste tu email, podés iniciar sesión.')
  })

  it('offers only a new link when the URL carries no token', async () => {
    const resends = answerResends()
    await renderApp('/verify-email')

    expect(await screen.findByRole('heading', { name: 'Este enlace no es válido' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Contraseña')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'rami@' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar nuevo enlace' }))
    expect(await screen.findByText('Ingresá un email válido.')).toBeInTheDocument()
    expect(resends).toHaveLength(0)
  })

  it('tells the user to wait when rate limited', async () => {
    answerVerify(() => problem(429, 'RATE_LIMITED'))
    await openVerifyLink()

    submitPassword()

    expect(await screen.findByRole('alert')).toHaveTextContent('Demasiados intentos. Probá de nuevo en 1 minuto.')
  })

  it.each([
    ['a busy service', () => problem(503, 'SERVICE_BUSY')],
    ['a validation error', () => problem(422, 'VALIDATION_ERROR')],
    ['a network failure', () => HttpResponse.error()],
  ])('shows a retryable error on %s', async (_, respond) => {
    answerVerify(respond)
    await openVerifyLink()

    submitPassword()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Verificar email' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Enviar nuevo enlace' })).not.toBeInTheDocument()
  })

  it('gives up on a verification that never answers after the timeout', async () => {
    const attempts: Request[] = []
    server.use(
      http.post(VERIFY_URL, async ({ request }) => {
        attempts.push(request)
        await delay('infinite')
      }),
    )
    await openVerifyLink()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

    submitPassword()
    await vi.waitFor(() => expect(attempts).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Verificando…' })).toBeDisabled()
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    vi.useRealTimers()

    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_ERROR)
    expect(screen.getByRole('button', { name: 'Verificar email' })).toBeEnabled()
  })
})
