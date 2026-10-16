import { act, render, screen } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { App } from '@/app'
import { router } from '@/router'
import { server } from '@/test/server'

const REFRESH_URL = '*/api/v1/auth/refresh'
const ERROR_HEADING = 'No pudimos completar el ingreso con Google'

function countRefreshes(status: 200 | 401) {
  const calls: Request[] = []
  server.use(
    http.post(REFRESH_URL, async ({ request }) => {
      calls.push(request)
      await delay(20)
      if (status === 401) return new HttpResponse(null, { status })
      return HttpResponse.json({ access_token: 'google-token', expires_in: 900, token_type: 'Bearer' })
    }),
  )
  return calls
}

async function renderComplete(hash = '') {
  render(<App />)
  await act(() => router.navigate({ to: '/auth/complete', hash }))
}

describe('/auth/complete', () => {
  it('shows the Google error state without refreshing when the callback reports a failure', async () => {
    const refreshes = countRefreshes(200)

    await renderComplete('error=oauth_failed')

    expect(await screen.findByRole('heading', { name: ERROR_HEADING })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Intentar de nuevo' })).toHaveAttribute(
      'href',
      '/api/v1/auth/google/start',
    )
    expect(screen.getByRole('link', { name: 'Ingresar con email' })).toHaveAttribute('href', '/login')
    expect(screen.queryByText(/Código de soporte/)).not.toBeInTheDocument()
    expect(refreshes).toHaveLength(0)
    expect(window.location.hash).toBe('')
  })

  it('shows the connecting state, refreshes once and lands on the dashboard', async () => {
    const refreshes = countRefreshes(200)

    await renderComplete()

    expect(await screen.findByText('Conectando con Google…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(refreshes).toHaveLength(1)
    expect(refreshes[0]?.headers.get('X-Requested-With')).toBe('investment-tracker')
  })

  // Runs after a test that leaves the shared router on the dashboard, so the page mounts with this hash.
  it('never renders text carried in the callback hash', async () => {
    countRefreshes(200)
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

    await renderComplete('error=INJECTED-ERROR&error_description=INJECTED-DESCRIPTION')
    expect(await screen.findByRole('heading', { name: ERROR_HEADING })).toBeInTheDocument()
    observer.disconnect()

    expect(rendered.join(' ')).not.toContain('INJECTED')
  })

  it('shows the Google error state when the refresh is rejected', async () => {
    const refreshes = countRefreshes(401)

    await renderComplete()

    expect(await screen.findByRole('heading', { name: ERROR_HEADING })).toBeInTheDocument()
    expect(refreshes).toHaveLength(1)
    expect(window.location.pathname).toBe('/auth/complete')
  })
})
