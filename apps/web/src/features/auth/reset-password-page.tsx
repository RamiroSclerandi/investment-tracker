import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { type ResetPasswordResult, resetPassword } from '@/features/auth/auth-api'
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

const resetSchema = z.object({ password: passwordSchema })

type ResetValues = z.infer<typeof resetSchema>
type Failure = Extract<ResetPasswordResult, 'unavailable'>

const GENERIC_ERROR = 'No pudimos guardar la contraseña. Probá de nuevo en unos minutos.'

export function ResetPasswordPage() {
  const navigate = useNavigate()
  const hash = useLocation({ select: (location) => location.hash })
  // Read once: the hash is cleared right away so the token never stays in the address bar or history.
  const [token] = useState(() => new URLSearchParams(hash).get('token'))

  useEffect(() => {
    if (hash) void navigate({ to: '/reset-password', replace: true })
  }, [hash, navigate])

  if (!token) return <InvalidLinkState />
  return <ResetForm token={token} />
}

function ResetForm({ token }: { token: string }) {
  const navigate = useNavigate()
  const [failure, setFailure] = useState<Failure | null>(null)
  const [invalid, setInvalid] = useState(false)
  const { register, handleSubmit, control, formState } = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: '' },
  })
  const { errors, isSubmitting } = formState
  const password = useWatch({ control, name: 'password' })

  const onSubmit = async ({ password: submitted }: ResetValues) => {
    setFailure(null)
    const result = await resetPassword({ token, password: submitted })
    if (result === 'reset') {
      await navigate({ to: '/login', search: { reset: true }, replace: true })
      return
    }
    if (result === 'invalid') {
      setInvalid(true)
      return
    }
    setFailure('unavailable')
  }

  if (invalid) return <InvalidLinkState />

  return (
    <div className="flex flex-1 flex-col gap-7">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Creá tu nueva contraseña</h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          Elegí la nueva contraseña para tu cuenta.
        </p>
      </div>
      <form noValidate onSubmit={(event) => void handleSubmit(onSubmit)(event)} className="flex flex-col gap-4">
        {failure && <FormAlert tone="error">{GENERIC_ERROR}</FormAlert>}
        <div className="flex flex-col gap-[7px]">
          <FieldLabel htmlFor="reset-password">Contraseña</FieldLabel>
          <PasswordInput
            id="reset-password"
            autoComplete="new-password"
            errorId="reset-password-error"
            hasError={errors.password !== undefined}
            {...register('password')}
          />
          <div className="flex justify-between gap-3">
            {errors.password ? (
              <FieldError id="reset-password-error" message={errors.password.message} />
            ) : (
              <span className="text-xs text-subtle-foreground">Entre 12 y 128 caracteres</span>
            )}
            <PasswordLength length={password.length} />
          </div>
        </div>
        <button type="submit" disabled={isSubmitting} className={primaryButtonClass}>
          {isSubmitting ? 'Guardando…' : 'Guardar contraseña'}
        </button>
      </form>
    </div>
  )
}

function InvalidLinkState() {
  return (
    <div className="flex flex-1 flex-col gap-[22px]">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">Este enlace no es válido</h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          Venció, ya se usó o está incompleto. Pedí uno nuevo y usalo dentro de los próximos 30 minutos.
        </p>
      </div>
      <Link to="/forgot-password" className={primaryButtonClass}>
        Pedir un enlace nuevo
      </Link>
      <Link to="/login" className={`${linkClass} mt-auto text-center text-sm`}>
        Volver a ingresar
      </Link>
    </div>
  )
}
