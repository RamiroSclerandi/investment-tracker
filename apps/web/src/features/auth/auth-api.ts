import { apiClient } from '@/api/client'
import type { components } from '@/api/generated/schema'
import { withTimeout } from '@/features/auth/request-timeout'

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
    const { data, error, response } = await withTimeout((signal) =>
      apiClient.POST('/api/v1/auth/login', { body, signal }),
    )
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

async function toAcceptedResult(
  send: (signal: AbortSignal) => Promise<{ response: Response }>,
): Promise<AcceptedResult> {
  try {
    const { response } = await withTimeout(send)
    if (response.status === 202) return 'accepted'
    return response.status === 429 ? 'rate-limited' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

export function register(body: Schemas['RegisterRequest']): Promise<AcceptedResult> {
  return toAcceptedResult((signal) => apiClient.POST('/api/v1/auth/register', { body, signal }))
}

export function resendVerification(email: string): Promise<AcceptedResult> {
  return toAcceptedResult((signal) =>
    apiClient.POST('/api/v1/auth/resend-verification', { body: { email }, signal }),
  )
}

export type VerifyResult = 'verified' | 'invalid' | 'rate-limited' | 'unavailable'

export async function verifyEmail(body: Schemas['VerifyEmailRequest']): Promise<VerifyResult> {
  try {
    const { data, response } = await withTimeout((signal) =>
      apiClient.POST('/api/v1/auth/verify-email', { body, signal }),
    )
    if (data) return 'verified'
    // The API answers the same 400 for a bad or used token and for a wrong password.
    if (response.status === 400) return 'invalid'
    return response.status === 429 ? 'rate-limited' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

export type ForgotResult = 'accepted' | 'unavailable'

export async function forgotPassword(email: string): Promise<ForgotResult> {
  try {
    const { response } = await withTimeout((signal) =>
      apiClient.POST('/api/v1/auth/password/forgot', { body: { email }, signal }),
    )
    // The API answers the same 202 whether or not the account exists, so every other status is retryable.
    return response.status === 202 ? 'accepted' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

export type ResetPasswordResult = 'reset' | 'invalid' | 'unavailable'

export async function resetPassword(body: Schemas['ResetPasswordRequest']): Promise<ResetPasswordResult> {
  try {
    const { response } = await withTimeout((signal) =>
      apiClient.POST('/api/v1/auth/password/reset', { body, signal }),
    )
    if (response.status === 204) return 'reset'
    if (response.status === 400) return 'invalid'
    return 'unavailable'
  } catch {
    return 'unavailable'
  }
}
