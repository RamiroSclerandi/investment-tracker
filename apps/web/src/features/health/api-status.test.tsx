import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { ApiStatus } from '@/features/health/api-status'
import { HEALTHZ_URL, server } from '@/test/server'

function renderStatus() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ApiStatus />
    </QueryClientProvider>,
  )
}

describe('ApiStatus', () => {
  it('shows a neutral state while the check is pending', () => {
    renderStatus()

    expect(screen.getByRole('status')).toHaveTextContent('Checking API')
  })

  it('shows "API online" when the health endpoint responds 200', async () => {
    renderStatus()

    expect(await screen.findByText('API online')).toBeInTheDocument()
  })

  it('shows "API offline" when the health endpoint responds 500', async () => {
    server.use(http.get(HEALTHZ_URL, () => new HttpResponse(null, { status: 500 })))
    renderStatus()

    expect(await screen.findByText('API offline')).toBeInTheDocument()
  })

  it('shows "API offline" on a network error', async () => {
    server.use(http.get(HEALTHZ_URL, () => HttpResponse.error()))
    renderStatus()

    expect(await screen.findByText('API offline')).toBeInTheDocument()
  })
})
