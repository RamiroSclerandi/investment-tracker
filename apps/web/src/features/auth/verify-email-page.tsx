import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { type VerifyResult, verifyEmail } from '@/features/auth/auth-api'
import {
  FieldError,
  FieldLabel,
  FormAlert,
  linkClass,
  PasswordInput,
  PasswordLength,
  primaryButtonClass,
} from '@/features/auth/auth-form-parts'
import { passwordSchema } from '@/features/auth/auth-schemas'
import { tokenFromHash } from '@/features/auth/hash-token'
import { ResendVerificationForm } from '@/features/auth/resend-verification-form'

const verifySchema = z.object({ password: passwordSchema })

type VerifyValues = z.infer<typeof verifySchema>
type Failure = Exclude<VerifyResult, 'verified'>

const FAILURE_MESSAGES: Record<Failure, string> = {
  invalid: 'Enlace inválido o contraseña incorrecta. Revisá la contraseña o pedí un enlace nuevo.',
  'rate-limited': 'Demasiados intentos. Probá de nuevo en 1 minuto.',
  unavailable: 'No pudimos verificar tu email. Probá de nuevo en unos minutos.',
}

export function VerifyEmailPage() {
  const navigate = useNavigate()
  const hash = useLocation({ select: (location) => location.hash })
  // Read once: the hash is cleared right away so the token never stays in the address bar or history.
  const [token] = useState(() => tokenFromHash(hash))

  useEffect(() => {
    if (hash) void navigate({ to: '/verify-email', replace: true })
  }, [hash, navigate])

  if (!token) return <InvalidLinkState />
  return <VerifyForm token={token} />
}

function VerifyForm({ token }: { token: string }) {
  const navigate = useNavigate()
  const [failure, setFailure] = useState<Failure | null>(null)
  const { register, handleSubmit, control, resetField, setFocus, formState } = useForm<VerifyValues>({
    resolver: zodResolver(verifySchema),
    defaultValues: { password: '' },
  })
  const { errors, isSubmitting } = formState
  const password = useWatch({ control, name: 'password' })

  const onSubmit = async ({ password: submitted }: VerifyValues) => {
    setFailure(null)
    const result = await verifyEmail({ token, password: submitted })
    if (result === 'verified') {
      await navigate({ to: '/login', search: { verified: true }, replace: true })
      return
    }
    setFailure(result)
    if (result === 'invalid') {
      resetField('password')
      setFocus('password')
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-7">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Verificá tu email</h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          Para confirmar tu email, ingresá la contraseña que elegiste al registrarte.
        </p>
      </div>
      <form noValidate onSubmit={(event) => void handleSubmit(onSubmit)(event)} className="flex flex-col gap-4">
        {failure && (
          <FormAlert tone={failure === 'rate-limited' ? 'warn' : 'error'}>{FAILURE_MESSAGES[failure]}</FormAlert>
        )}
        <div className="flex flex-col gap-[7px]">
          <FieldLabel htmlFor="verify-password">Contraseña</FieldLabel>
          <PasswordInput
            id="verify-password"
            autoComplete="current-password"
            errorId="verify-password-error"
            hasError={errors.password !== undefined}
            {...register('password')}
          />
          <div className="flex justify-between gap-3">
            {errors.password ? (
              <FieldError id="verify-password-error" message={errors.password.message} />
            ) : (
              <span className="text-xs text-subtle-foreground">Entre 12 y 128 caracteres</span>
            )}
            <PasswordLength length={password.length} />
          </div>
        </div>
        <button type="submit" disabled={isSubmitting} className={primaryButtonClass}>
          {isSubmitting ? 'Verificando…' : 'Verificar email'}
        </button>
      </form>
      {failure === 'invalid' && (
        <section className="flex flex-col gap-3 border-t border-border pt-5">
          <p className="text-sm text-muted-foreground">¿El enlace venció o ya se usó? Pedí uno nuevo.</p>
          <ResendVerificationForm />
          <p className="text-sm text-muted-foreground">
            Si ya verificaste tu email, <Link to="/login" className={linkClass}>podés iniciar sesión</Link>.
          </p>
        </section>
      )}
    </div>
  )
}

function InvalidLinkState() {
  return (
    <div className="flex flex-1 flex-col gap-[22px]">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">Este enlace no es válido</h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          Venció, ya se usó o está incompleto. Pedí uno nuevo y usalo dentro de las próximas 24 horas.
        </p>
      </div>
      <ResendVerificationForm />
      <Link to="/login" className={`${linkClass} mt-auto text-center text-sm`}>
        Volver a ingresar
      </Link>
    </div>
  )
}
