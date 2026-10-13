import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from '@/app'

describe('App', () => {
  it('renders the placeholder heading on the index route', async () => {
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: /investment tracker/i }),
    ).toBeInTheDocument()
  })
})
