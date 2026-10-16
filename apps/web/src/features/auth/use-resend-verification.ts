import { useEffect, useState } from 'react'
import { type AcceptedResult, resendVerification } from '@/features/auth/auth-api'

// Matches the API's per-IP resend limit, so a waiting user is not sent straight into a 429.
const COOLDOWN_SECONDS = 60

export function useResendVerification(initialCooldownSeconds = 0) {
  const [result, setResult] = useState<AcceptedResult | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(initialCooldownSeconds)

  useEffect(() => {
    if (secondsLeft <= 0) return undefined
    const timer = setTimeout(() => setSecondsLeft((seconds) => seconds - 1), 1_000)
    return () => clearTimeout(timer)
  }, [secondsLeft])

  const resend = async (email: string) => {
    setIsSending(true)
    const outcome = await resendVerification(email)
    setIsSending(false)
    setResult(outcome)
    if (outcome !== 'unavailable') setSecondsLeft(COOLDOWN_SECONDS)
  }

  return { result, isSending, secondsLeft, isBlocked: isSending || secondsLeft > 0, resend }
}

export type ResendState = ReturnType<typeof useResendVerification>
