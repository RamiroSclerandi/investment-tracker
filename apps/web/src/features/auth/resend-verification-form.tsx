import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { FieldError, FieldLabel, TextInput } from '@/features/auth/auth-form-parts'
import { emailSchema } from '@/features/auth/auth-schemas'
import { ResendButton, ResendResult } from '@/features/auth/resend-verification-parts'
import { useResendVerification } from '@/features/auth/use-resend-verification'

const resendSchema = z.object({ email: emailSchema })

type ResendValues = z.infer<typeof resendSchema>

// The verification token does not reveal its address, so the user types the email to send a new link to.
export function ResendVerificationForm() {
  const resendState = useResendVerification()
  const { register, handleSubmit, formState } = useForm<ResendValues>({
    resolver: zodResolver(resendSchema),
    defaultValues: { email: '' },
  })

  return (
    <form
      noValidate
      onSubmit={(event) => void handleSubmit(({ email }) => resendState.resend(email))(event)}
      className="flex flex-col gap-3"
    >
      <div className="flex flex-col gap-[7px]">
        <FieldLabel htmlFor="resend-email">Email</FieldLabel>
        <TextInput
          id="resend-email"
          type="email"
          autoComplete="email"
          placeholder="vos@ejemplo.com"
          errorId="resend-email-error"
          hasError={formState.errors.email !== undefined}
          {...register('email')}
        />
        <FieldError id="resend-email-error" message={formState.errors.email?.message} />
      </div>
      <ResendResult state={resendState} />
      <ResendButton
        type="submit"
        state={resendState}
        label="Enviar nuevo enlace"
        className="h-12 rounded-xl border border-border-strong text-[15px] font-medium disabled:opacity-60"
      />
    </form>
  )
}
