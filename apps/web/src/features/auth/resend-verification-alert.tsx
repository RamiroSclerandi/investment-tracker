import { ResendButton, ResendResult } from '@/features/auth/resend-verification-parts'
import { useResendVerification } from '@/features/auth/use-resend-verification'

export function ResendVerificationAlert({ email }: { email: string }) {
  const resendState = useResendVerification(email)

  return (
    <div role="alert" className="flex flex-col gap-3 rounded-[14px] border border-warn/30 bg-warn/10 p-3.5">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold text-warn">Verificá tu email para continuar</span>
        <span className="text-[13px] leading-[1.45] text-muted-foreground">
          Abrí el enlace que te enviamos al registrarte. Vence a las 24 horas.
        </span>
      </div>
      <ResendResult state={resendState} />
      <ResendButton
        type="button"
        state={resendState}
        label="Reenviar email de verificación"
        onClick={() => void resendState.resend(email)}
        className="h-11 rounded-xl border border-warn/40 text-sm font-semibold text-warn disabled:opacity-60"
      />
    </div>
  )
}
