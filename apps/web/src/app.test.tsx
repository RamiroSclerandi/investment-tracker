import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { renderApp } from '@/test/render-app'
import { server } from '@/test/server'

const BRAND_TAGLINE = 'Tu cartera de cripto y mercado argentino, en vivo.'

async function renderSignedIn(path: string) {
  server.use(
    http.post('*/api/v1/auth/refresh', () =>
      HttpResponse.json({ access_token: 'token', expires_in: 900, token_type: 'Bearer' }),
    ),
  )
  const rendered = await renderApp(path)
  await rendered.session.refreshSession()
  return rendered
}

describe('App', () => {
  it('renders the dashboard heading inside the shell on the index route', async () => {
    await renderSignedIn('/')

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
  })

  it('renders the transactions heading inside the shell', async () => {
    await renderSignedIn('/transactions')

    expect(await screen.findByRole('heading', { name: 'Transactions' })).toBeInTheDocument()
    expect(screen.getByRole('banner')).toHaveTextContent('Investment Tracker')
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
  })

  it('redirects an anonymous visitor from a protected route to /login', async () => {
    server.use(http.post('*/api/v1/auth/refresh', () => new HttpResponse(null, { status: 401 })))
    const { router, session } = await renderApp('/')

    await session.refreshSession()

    expect(await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(screen.queryByRole('heading', { name: 'Dashboard' })).not.toBeInTheDocument()
  })

  it('shows the loading state without redirecting while the session is unknown', async () => {
    const { router } = await renderApp('/transactions')

    expect(await screen.findByRole('status', { name: 'Cargando tu sesión' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Transactions' })).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/transactions')
  })

  it('renders /login in the brand split layout without the app navigation', async () => {
    await renderApp('/login')

    expect(await screen.findByRole('heading', { name: 'Ingresá a tu cuenta' })).toBeInTheDocument()
    expect(screen.getByText(BRAND_TAGLINE)).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
    expect(screen.queryByRole('banner')).not.toBeInTheDocument()
  })

  it('keeps the other auth routes inside the same layout', async () => {
    await renderApp('/forgot-password')

    expect(await screen.findByRole('heading', { name: 'Forgot password' })).toBeInTheDocument()
    expect(screen.getByText(BRAND_TAGLINE)).toBeInTheDocument()
  })
})
