import { useState } from 'react'
import { type AcceptedResult, resendVerification } from '@/features/auth/auth-api'

const RESULT_MESSAGES: Record<AcceptedResult, string> = {
  accepted: 'Si la cuenta está pendiente de verificación, te enviamos un nuevo enlace.',
  'rate-limited': 'Demasiados intentos. Probá de nuevo en 1 minuto.',
  unavailable: 'No pudimos reenviar el email. Probá de nuevo en unos minutos.',
}

export function ResendVerificationAlert({ getEmail }: { getEmail: () => string }) {
  const [result, setResult] = useState<AcceptedResult | 'sending' | null>(null)

  const resend = async () => {
    setResult('sending')
    setResult(await resendVerification(getEmail()))
  }

  return (
    <div role="alert" className="flex flex-col gap-3 rounded-[14px] border border-warn/30 bg-warn/10 p-3.5">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold text-warn">Verificá tu email para continuar</span>
        <span className="text-[13px] leading-[1.45] text-muted-foreground">
          Abrí el enlace que te enviamos al registrarte. Vence a las 24 horas.
        </span>
      </div>
      {result !== null && result !== 'sending' ? (
        <p role="status" className="text-[13px] leading-[1.45]">
          {RESULT_MESSAGES[result]}
        </p>
      ) : (
        <button
          type="button"
          disabled={result === 'sending'}
          onClick={() => void resend()}
          className="h-11 rounded-xl border border-warn/40 text-sm font-semibold text-warn disabled:opacity-60"
        >
          Reenviar email de verificación
        </button>
      )}
    </div>
  )
}
