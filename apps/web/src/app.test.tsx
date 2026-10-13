import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from '@/app'
import { router } from '@/router'

async function renderAt(path: string) {
  render(<App />)
  await act(() => router.navigate({ to: path }))
}

describe('App', () => {
  it('renders the dashboard heading inside the shell on the index route', async () => {
    await renderAt('/')

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
  })

  it('renders the transactions heading inside the shell', async () => {
    await renderAt('/transactions')

    expect(await screen.findByRole('heading', { name: 'Transactions' })).toBeInTheDocument()
    expect(screen.getByRole('banner')).toHaveTextContent('Investment Tracker')
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
  })

  it('renders /login without the app navigation', async () => {
    await renderAt('/login')

    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
    expect(screen.queryByRole('banner')).not.toBeInTheDocument()
  })
})
