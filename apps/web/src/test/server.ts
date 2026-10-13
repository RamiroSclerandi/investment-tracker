import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const HEALTHZ_URL = '*/api/v1/healthz'

export const server = setupServer(
  http.get(HEALTHZ_URL, () => HttpResponse.json({ status: 'ok' })),
)
