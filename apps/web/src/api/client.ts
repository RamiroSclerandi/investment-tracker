import createClient from 'openapi-fetch'
import type { paths } from '@/api/generated/schema'
import { authMiddleware } from '@/features/auth/auth-middleware'

// Absolute same-origin base: openapi-fetch builds a Request, which Node (tests) cannot resolve from a relative URL.
export const apiClient = createClient<paths>({ baseUrl: window.location.origin })
apiClient.use(authMiddleware)
