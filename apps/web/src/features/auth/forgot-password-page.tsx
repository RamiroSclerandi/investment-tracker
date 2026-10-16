import { zodResolver } from '@hookform/resolvers/zod'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { BrandMark } from '@/components/brand-mark'
import { forgotPassword } from '@/features/auth/auth-api'
import {
  FieldError,
  FieldLabel,
  FormAlert,
  linkClass,
  primaryButtonClass,
  TextInput,
} from '@/features/auth/auth-form-parts'
import { emailSchema } from '@/features/auth/auth-schemas'

const forgotSchema = z.object({ email: emailSchema })

type ForgotValues = z.infer<typeof forgotSchema>

const GENERIC_ERROR = 'No pudimos enviar el email. Probá de nuevo en unos minutos.'

export function ForgotPasswordPage() {
  const [failed, setFailed] = useState(false)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const { register, handleSubmit, formState } = useForm<ForgotValues>({
    resolver: zodResolver(forgotSchema),
    defaultValues: { email: '' },
  })
  const { errors, isSubmitting } = formState

  const onSubmit = async ({ email }: ForgotValues) => {
    setFailed(false)
    const result = await forgotPassword(email)
    if (result === 'accepted') setSentTo(email)
    else setFailed(true)
  }

  if (sentTo !== null) return <EmailSentState email={sentTo} />

  return (
    <div className="flex flex-1 flex-col gap-6">
      <div className="flex flex-col gap-[18px]">
        <BrandMark className="lg:hidden" />
        <div className="flex flex-col gap-1.5">
          <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Recuperá tu contraseña</h1>
          <p className="text-sm text-muted-foreground">
            Ingresá tu email y te enviamos un enlace para crear una nueva contraseña.
          </p>
        </div>
      </div>
      <form noValidate onSubmit={(event) => void handleSubmit(onSubmit)(event)} className="flex flex-col gap-4">
        {failed && <FormAlert tone="error">{GENERIC_ERROR}</FormAlert>}
        <div className="flex flex-col gap-[7px]">
          <FieldLabel htmlFor="forgot-email">Email</FieldLabel>
          <TextInput
            id="forgot-email"
            type="email"
            autoComplete="email"
            placeholder="vos@ejemplo.com"
            errorId="forgot-email-error"
            hasError={errors.email !== undefined}
            {...register('email')}
          />
          <FieldError id="forgot-email-error" message={errors.email?.message} />
        </div>
        <button type="submit" disabled={isSubmitting} className={primaryButtonClass}>
          {isSubmitting ? 'Enviando…' : 'Enviar enlace'}
        </button>
      </form>
      <p className="mt-auto text-center text-sm text-muted-foreground">
        ¿La recordás?{' '}
        <Link to="/login" className={linkClass}>
          Ingresá
        </Link>
      </p>
    </div>
  )
}

function EmailSentState({ email }: { email: string }) {
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
          Si hay una cuenta asociada a <span className="font-medium text-foreground">{email}</span>, te enviamos un
          enlace para crear una nueva contraseña. Vence en 30 minutos.
        </p>
        {/* Requests over the hourly cap are silently dropped, so an immediate retry would never help. */}
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          ¿No llega? Esperá unos minutos antes de pedirlo de nuevo: enviamos una cantidad limitada de emails por
          hora.
        </p>
      </div>
      <Link to="/login" className={`${linkClass} mt-auto text-center text-sm`}>
        Volver a ingresar
      </Link>
    </div>
  )
}
