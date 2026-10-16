import { Link } from '@tanstack/react-router'
import { linkClass } from '@/features/auth/auth-form-parts'
import { ResendButton, ResendResult } from '@/features/auth/resend-verification-parts'
import { useResendVerification } from '@/features/auth/use-resend-verification'

// The cooldown starts at once: an email was just requested, so an immediate resend would only hit the rate limit.
const INITIAL_COOLDOWN_SECONDS = 60

export function VerifySentState({ email }: { email: string }) {
  const resendState = useResendVerification(INITIAL_COOLDOWN_SECONDS)

  return (
    <div className="flex flex-1 flex-col gap-[22px]">
      <span className="grid size-[72px] place-items-center rounded-[22px] bg-primary/12">
        <svg
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          className="text-primary"
          aria-hidden="true"
        >
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="m3 7 9 6 9-6" />
        </svg>
      </span>
      <div className="flex flex-col gap-2.5">
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">Revisá tu email</h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          Si el registro puede completarse, vas a recibir un enlace en{' '}
          <span className="font-medium text-foreground">{email}</span> para verificar tu cuenta. Vence en 24
          horas.
        </p>
      </div>
      <ResendResult state={resendState} />
      <div className="flex flex-col gap-2.5">
        <ResendButton
          type="button"
          state={resendState}
          label="Reenviar email"
          onClick={() => void resendState.resend(email)}
          className="h-12 rounded-xl border border-border-strong text-[15px] font-medium disabled:opacity-60"
        />
        <p className="text-center text-[13px] text-muted-foreground">¿No llega? Revisá spam o promociones.</p>
      </div>
      <Link to="/login" className={`${linkClass} mt-auto text-center text-sm`}>
        Volver a ingresar
      </Link>
    </div>
  )
}
