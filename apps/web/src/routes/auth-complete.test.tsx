import { fireEvent, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/server'
import { renderApp } from '@/test/render-app'

const REFRESH_URL = '*/api/v1/auth/refresh'
const ERROR_HEADING = 'No pudimos completar el ingreso con Google'
const UNREACHABLE_HEADING = 'No pudimos conectar'

function answerRefreshes(...statuses: (200 | 401 | 503)[]) {
  const calls: Request[] = []
  server.use(
    http.post(REFRESH_URL, async ({ request }) => {
      calls.push(request)
      await delay(20)
      const status = statuses[Math.min(calls.length, statuses.length) - 1] ?? 200
      if (status !== 200) return new HttpResponse(null, { status })
      return HttpResponse.json({ access_token: 'google-token', expires_in: 900, token_type: 'Bearer' })
    }),
  )
  return calls
}

describe('/auth/complete', () => {
  it('shows the Google error state without refreshing when the callback reports a failure', async () => {
    const refreshes = answerRefreshes(200)

    const { router } = await renderApp('/auth/complete#error=oauth_failed')

    expect(await screen.findByRole('heading', { name: ERROR_HEADING })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Intentar de nuevo' })).toHaveAttribute(
      'href',
      '/api/v1/auth/google/start',
    )
    expect(screen.getByRole('link', { name: 'Ingresar con email' })).toHaveAttribute('href', '/login')
    expect(screen.queryByText(/Código de soporte/)).not.toBeInTheDocument()
    expect(refreshes).toHaveLength(0)
    expect(router.state.location.hash).toBe('')
  })

  it('shows the connecting state, refreshes once and lands on the dashboard', async () => {
    const refreshes = answerRefreshes(200)

    await renderApp('/auth/complete')

    expect(await screen.findByText('Conectando con Google…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(refreshes).toHaveLength(1)
    expect(refreshes[0]?.headers.get('X-Requested-With')).toBe('investment-tracker')
  })

  it('never renders text carried in the callback hash', async () => {
    answerRefreshes(200)
    const rendered: string[] = []
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        rendered.push(mutation.target.textContent ?? '', mutation.oldValue ?? '')
        mutation.removedNodes.forEach((node) => rendered.push(node.textContent ?? ''))
      })
    })
    observer.observe(document.body, {
      childList: true,
      characterData: true,
      characterDataOldValue: true,
      subtree: true,
    })

    await renderApp('/auth/complete#error=INJECTED-ERROR&error_description=INJECTED-DESCRIPTION')
    expect(await screen.findByRole('heading', { name: ERROR_HEADING })).toBeInTheDocument()
    observer.disconnect()

    expect(rendered.join(' ')).not.toContain('INJECTED')
  })

  it('shows the Google error state when the refresh is rejected', async () => {
    const refreshes = answerRefreshes(401)

    const { router } = await renderApp('/auth/complete')

    expect(await screen.findByRole('heading', { name: ERROR_HEADING })).toBeInTheDocument()
    expect(refreshes).toHaveLength(1)
    expect(router.state.location.pathname).toBe('/auth/complete')
  })

  it('offers a retry instead of the expired state when the refresh fails transiently', async () => {
    const refreshes = answerRefreshes(503, 200)

    await renderApp('/auth/complete')

    expect(await screen.findByRole('heading', { name: UNREACHABLE_HEADING })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: ERROR_HEADING })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(refreshes).toHaveLength(2)
  })

  it('shows the retry state when the refresh answers with a non-JSON body', async () => {
    server.use(http.post(REFRESH_URL, () => new HttpResponse('<html />', { status: 200 })))

    await renderApp('/auth/complete')

    expect(await screen.findByRole('heading', { name: UNREACHABLE_HEADING })).toBeInTheDocument()
  })
})
