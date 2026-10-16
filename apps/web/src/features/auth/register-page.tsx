import { zodResolver } from '@hookform/resolvers/zod'
import { Link, Navigate } from '@tanstack/react-router'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { BrandMark } from '@/components/brand-mark'
import { register as registerAccount } from '@/features/auth/auth-api'
import {
  EmailDivider,
  FieldError,
  FieldLabel,
  FormAlert,
  GoogleLink,
  linkClass,
  PasswordInput,
  PasswordLength,
  primaryButtonClass,
  TextInput,
} from '@/features/auth/auth-form-parts'
import { emailSchema, passwordSchema } from '@/features/auth/auth-schemas'
import { VerifySentState } from '@/features/auth/verify-sent-state'
import { useAuthStatus } from '@/features/auth/use-auth-status'

const registerSchema = z.object({
  display_name: z
    .string()
    .trim()
    .min(1, { error: 'Ingresá tu nombre.' })
    .max(80, { error: 'Usá hasta 80 caracteres.' }),
  email: emailSchema,
  password: passwordSchema,
})

type RegisterValues = z.infer<typeof registerSchema>
type Failure = 'rate-limited' | 'unavailable'

const FAILURE_MESSAGES: Record<Failure, string> = {
  'rate-limited': 'Demasiados intentos. Probá de nuevo en 1 minuto.',
  unavailable: 'No pudimos crear la cuenta. Probá de nuevo en unos minutos.',
}

export function RegisterPage() {
  const status = useAuthStatus()
  const [failure, setFailure] = useState<Failure | null>(null)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const { register, handleSubmit, control, formState } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { display_name: '', email: '', password: '' },
  })
  const { errors, isSubmitting } = formState
  const password = useWatch({ control, name: 'password' })

  const onSubmit = async (values: RegisterValues) => {
    setFailure(null)
    const result = await registerAccount(values)
    if (result === 'accepted') setSentTo(values.email)
    else setFailure(result)
  }

  if (status === 'authenticated') return <Navigate to="/" replace />
  if (sentTo !== null) return <VerifySentState email={sentTo} />

  return (
    <div className="flex flex-1 flex-col gap-6">
      <div className="flex flex-col gap-[18px]">
        <BrandMark className="lg:hidden" />
        <div className="flex flex-col gap-1.5">
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Creá tu cuenta</h1>
          <p className="text-sm text-muted-foreground">Vas a necesitar verificar tu email.</p>
        </div>
      </div>
      <form noValidate onSubmit={(event) => void handleSubmit(onSubmit)(event)} className="flex flex-col gap-4">
        {failure && (
          <FormAlert tone={failure === 'rate-limited' ? 'warn' : 'error'}>{FAILURE_MESSAGES[failure]}</FormAlert>
        )}
        <GoogleLink>Registrarme con Google</GoogleLink>
        <EmailDivider />
        <div className="flex flex-col gap-[7px]">
          <FieldLabel htmlFor="register-name">Nombre</FieldLabel>
          <TextInput
            id="register-name"
            autoComplete="name"
            errorId="register-name-error"
            hasError={errors.display_name !== undefined}
            {...register('display_name')}
          />
          <FieldError id="register-name-error" message={errors.display_name?.message} />
        </div>
        <div className="flex flex-col gap-[7px]">
          <FieldLabel htmlFor="register-email">Email</FieldLabel>
          <TextInput
            id="register-email"
            type="email"
            autoComplete="email"
            placeholder="vos@ejemplo.com"
            errorId="register-email-error"
            hasError={errors.email !== undefined}
            {...register('email')}
          />
          <FieldError id="register-email-error" message={errors.email?.message} />
        </div>
        <div className="flex flex-col gap-[7px]">
          <FieldLabel htmlFor="register-password">Contraseña</FieldLabel>
          <PasswordInput
            id="register-password"
            autoComplete="new-password"
            errorId="register-password-error"
            hasError={errors.password !== undefined}
            {...register('password')}
          />
          <div className="flex justify-between gap-3">
            <FieldError id="register-password-error" message={errors.password?.message} />
            <PasswordLength length={password.length} />
          </div>
        </div>
        <button type="submit" disabled={isSubmitting} className={primaryButtonClass}>
          {isSubmitting ? 'Creando cuenta…' : 'Crear cuenta'}
        </button>
      </form>
      <p className="mt-auto text-center text-sm text-muted-foreground">
        ¿Ya tenés cuenta?{' '}
        <Link to="/login" className={linkClass}>
          Ingresá
        </Link>
      </p>
    </div>
  )
}
