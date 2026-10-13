import createClient from 'openapi-fetch'
import type { paths } from '@/api/generated/schema'

// Absolute same-origin base: openapi-fetch builds a Request, which Node (tests) cannot resolve from a relative URL.
export const apiClient = createClient<paths>({ baseUrl: window.location.origin })
