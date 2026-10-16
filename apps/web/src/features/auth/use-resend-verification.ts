import { useEffect, useRef, useState } from 'react'
import { type AcceptedResult, resendVerification } from '@/features/auth/auth-api'

// Matches the API's per-IP resend limit, so a waiting user is not sent straight into a 429.
const COOLDOWN_SECONDS = 60

// Keyed by address so the wait survives remounts without ever blocking a different address.
const cooldownEndsAt = new Map<string, number>()

function remainingSeconds(email: string): number {
  const endsAt = cooldownEndsAt.get(email)
  return endsAt === undefined ? 0 : Math.max(0, Math.ceil((endsAt - Date.now()) / 1_000))
}

type Cooldown = { email: string; secondsLeft: number }

function seedCooldown(email: string, initialCooldownSeconds: number): Cooldown {
  const remaining = remainingSeconds(email)
  if (initialCooldownSeconds > remaining) {
    cooldownEndsAt.set(email, Date.now() + initialCooldownSeconds * 1_000)
    return { email, secondsLeft: initialCooldownSeconds }
  }
  return { email, secondsLeft: remaining }
}

export function useResendVerification(email: string, initialCooldownSeconds = 0) {
  const normalizedEmail = email.trim().toLowerCase()
  const [result, setResult] = useState<AcceptedResult | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [cooldown, setCooldown] = useState<Cooldown>(() => seedCooldown(normalizedEmail, initialCooldownSeconds))
  const secondsLeft = cooldown.email === normalizedEmail ? cooldown.secondsLeft : remainingSeconds(normalizedEmail)
  const isMounted = useRef(false)

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
    }
  }, [])

  useEffect(() => {
    if (secondsLeft <= 0) return undefined
    const timer = setTimeout(
      () => setCooldown({ email: normalizedEmail, secondsLeft: Math.max(0, secondsLeft - 1) }),
      1_000,
    )
    return () => clearTimeout(timer)
  }, [secondsLeft, normalizedEmail])

  const resend = async (address: string) => {
    const normalizedAddress = address.trim().toLowerCase()
    setIsSending(true)
    const outcome = await resendVerification(address)
    // Arm the shared cooldown even after unmount, so a remounted form cannot resend straight away.
    if (outcome !== 'unavailable') {
      cooldownEndsAt.set(normalizedAddress, Date.now() + COOLDOWN_SECONDS * 1_000)
    }
    if (!isMounted.current) return
    setIsSending(false)
    setResult(outcome)
    setCooldown({ email: normalizedEmail, secondsLeft: remainingSeconds(normalizedEmail) })
  }

  return { result, isSending, secondsLeft, isBlocked: isSending || secondsLeft > 0, resend }
}

export type ResendState = ReturnType<typeof useResendVerification>
