import { zodResolver } from '@hookform/resolvers/zod'
import { Link, Navigate } from '@tanstack/react-router'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { BrandMark } from '@/components/brand-mark'
import { type LoginResult, logIn } from '@/features/auth/auth-api'
import {
  EmailDivider,
  FieldError,
  FieldLabel,
  FormAlert,
  GoogleLink,
  linkClass,
  PasswordInput,
  primaryButtonClass,
  TextInput,
} from '@/features/auth/auth-form-parts'
import { ResendVerificationAlert } from '@/features/auth/resend-verification-alert'
import { signIn } from '@/features/auth/session'
import { useAuthStatus } from '@/features/auth/use-auth-status'

const loginSchema = z.object({
  email: z.email({ error: 'Ingresá un email válido.' }),
  password: z.string().min(1, { error: 'Ingresá tu contraseña.' }),
})

type LoginValues = z.infer<typeof loginSchema>
type Failure = Exclude<LoginResult['kind'], 'signed-in'>

const FAILURE_MESSAGES: Record<Exclude<Failure, 'unverified'>, string> = {
  invalid: 'Email o contraseña incorrectos.',
  'rate-limited': 'Demasiados intentos. Probá de nuevo en 1 minuto.',
  unavailable: 'No pudimos ingresar. Probá de nuevo en unos minutos.',
}

export function LoginPage() {
  const status = useAuthStatus()
  const [failure, setFailure] = useState<Failure | null>(null)
  const [submittedEmail, setSubmittedEmail] = useState('')
  const { register, handleSubmit, resetField, setFocus, formState } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })
  const { errors, isSubmitting } = formState

  const onSubmit = async (values: LoginValues) => {
    setFailure(null)
    const result = await logIn(values)
    if (result.kind === 'signed-in') {
      signIn(result.accessToken)
      return
    }
    setSubmittedEmail(values.email)
    setFailure(result.kind)
    if (result.kind === 'invalid') {
      resetField('password')
      setFocus('password')
    }
  }

  if (status === 'authenticated') return <Navigate to="/" replace />

  return (
    <div className="flex flex-1 flex-col gap-7">
      <div className="flex flex-col gap-[18px]">
        <BrandMark className="lg:hidden" />
        <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Ingresá a tu cuenta</h1>
      </div>
      <form noValidate onSubmit={(event) => void handleSubmit(onSubmit)(event)} className="flex flex-col gap-4">
        {failure === 'unverified' ? (
          <ResendVerificationAlert email={submittedEmail} />
        ) : (
          failure && (
            <FormAlert tone={failure === 'rate-limited' ? 'warn' : 'error'}>{FAILURE_MESSAGES[failure]}</FormAlert>
          )
        )}
        <GoogleLink>Continuar con Google</GoogleLink>
        <EmailDivider />
        <div className="flex flex-col gap-[7px]">
          <FieldLabel htmlFor="login-email">Email</FieldLabel>
          <TextInput
            id="login-email"
            type="email"
            autoComplete="email"
            placeholder="vos@ejemplo.com"
            errorId="login-email-error"
            hasError={errors.email !== undefined}
            {...register('email')}
          />
          <FieldError id="login-email-error" message={errors.email?.message} />
        </div>
        <div className="flex flex-col gap-[7px]">
          <div className="flex items-center justify-between">
            <FieldLabel htmlFor="login-password">Contraseña</FieldLabel>
            <Link to="/forgot-password" className={`${linkClass} py-1.5 text-[13px]`}>
              ¿La olvidaste?
            </Link>
          </div>
          <PasswordInput
            id="login-password"
            autoComplete="current-password"
            errorId="login-password-error"
            hasError={errors.password !== undefined}
            {...register('password')}
          />
          <FieldError id="login-password-error" message={errors.password?.message} />
        </div>
        <button type="submit" disabled={isSubmitting} className={primaryButtonClass}>
          {isSubmitting ? 'Ingresando…' : 'Ingresar'}
        </button>
      </form>
      <p className="mt-auto text-center text-sm text-muted-foreground">
        ¿No tenés cuenta?{' '}
        <Link to="/register" className={linkClass}>
          Creá una
        </Link>
      </p>
    </div>
  )
}
