import { apiClient } from '@/api/client'
import type { components } from '@/api/generated/schema'

type Schemas = components['schemas']

export type LoginResult =
  | { kind: 'signed-in'; accessToken: string }
  | { kind: 'invalid' | 'unverified' | 'rate-limited' | 'unavailable' }

export type AcceptedResult = 'accepted' | 'rate-limited' | 'unavailable'

function problemCode(error: unknown): unknown {
  return typeof error === 'object' && error !== null && 'code' in error ? error.code : undefined
}

export async function logIn(body: Schemas['LoginRequest']): Promise<LoginResult> {
  try {
    const { data, error, response } = await apiClient.POST('/api/v1/auth/login', { body })
    if (data) return { kind: 'signed-in', accessToken: data.access_token }
    if (response.status === 401) return { kind: 'invalid' }
    if (response.status === 403 && problemCode(error) === 'EMAIL_NOT_VERIFIED') {
      return { kind: 'unverified' }
    }
    return { kind: response.status === 429 ? 'rate-limited' : 'unavailable' }
  } catch {
    return { kind: 'unavailable' }
  }
}

async function toAcceptedResult(request: Promise<{ response: Response }>): Promise<AcceptedResult> {
  try {
    const { response } = await request
    if (response.status === 202) return 'accepted'
    return response.status === 429 ? 'rate-limited' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

export function register(body: Schemas['RegisterRequest']): Promise<AcceptedResult> {
  return toAcceptedResult(apiClient.POST('/api/v1/auth/register', { body }))
}

export function resendVerification(email: string): Promise<AcceptedResult> {
  return toAcceptedResult(apiClient.POST('/api/v1/auth/resend-verification', { body: { email } }))
}
