import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach } from 'vitest'
import { server } from '@/test/server'

// Started at import time: openapi-fetch captures global fetch when the client module loads.
server.listen({ onUnhandledFrame: 'error' })
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())

window.scrollTo = () => undefined
