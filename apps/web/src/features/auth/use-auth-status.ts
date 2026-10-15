import { useSyncExternalStore } from 'react'
import { type AuthStatus, getAuthStatus, subscribeAuthStatus } from '@/features/auth/session'

export function useAuthStatus(): AuthStatus {
  return useSyncExternalStore(subscribeAuthStatus, getAuthStatus)
}
