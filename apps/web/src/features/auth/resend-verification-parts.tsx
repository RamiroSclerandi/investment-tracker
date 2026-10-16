import type { ComponentProps } from 'react'
import type { AcceptedResult } from '@/features/auth/auth-api'
import type { ResendState } from '@/features/auth/use-resend-verification'

const RESULT_MESSAGES: Record<AcceptedResult, string> = {
  accepted: 'Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.',
  'rate-limited': 'Demasiados intentos. Probá de nuevo en 1 minuto.',
  unavailable: 'No pudimos reenviar el email. Probá de nuevo en unos minutos.',
}

function formatCountdown(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function ResendResult({ state }: { state: ResendState }) {
  if (state.result === null) return null
  return (
    <p role="status" className="text-[13px] leading-[1.45]">
      {RESULT_MESSAGES[state.result]}
    </p>
  )
}

type ResendButtonProps = Omit<ComponentProps<'button'>, 'disabled' | 'children'> & {
  state: ResendState
  label: string
}

export function ResendButton({ state, label, ...props }: ResendButtonProps) {
  return (
    <button {...props} disabled={state.isBlocked}>
      {state.secondsLeft > 0 ? `Reenviar en ${formatCountdown(state.secondsLeft)}` : label}
    </button>
  )
}
