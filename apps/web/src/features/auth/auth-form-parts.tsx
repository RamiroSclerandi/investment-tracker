import { type ComponentProps, type ReactNode, useState } from 'react'
import { PASSWORD_MIN_LENGTH } from '@/features/auth/auth-schemas'
import { cn } from '@/lib/utils'

export const GOOGLE_START_URL = '/api/v1/auth/google/start'

export const linkClass = 'text-[#f59be6] underline-offset-4 hover:underline'

const inputClass =
  'h-12 w-full rounded-xl border border-border-strong bg-secondary px-3.5 text-base outline-none focus-visible:border-primary focus-visible:ring-[3px] focus-visible:ring-primary/20 aria-invalid:border-destructive'

export const primaryButtonClass =
  'mt-1.5 h-[52px] rounded-[14px] bg-primary text-base font-semibold text-primary-foreground disabled:opacity-60'

export function GoogleLink({ children }: { children: ReactNode }) {
  return (
    <a
      href={GOOGLE_START_URL}
      className="flex h-12 items-center justify-center gap-2.5 rounded-xl border border-border-strong bg-secondary text-[15px] font-medium"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="#4285F4" d="M22.5 12.3c0-.8-.1-1.5-.2-2.2H12v4.2h5.9a5 5 0 0 1-2.2 3.3v2.7h3.5c2.1-1.9 3.3-4.7 3.3-8Z" />
        <path fill="#34A853" d="M12 23c3 0 5.5-1 7.2-2.7l-3.5-2.7c-1 .7-2.2 1-3.7 1-2.8 0-5.2-1.9-6.1-4.5H2.3v2.8A11 11 0 0 0 12 23Z" />
        <path fill="#FBBC05" d="M5.9 14.1a6.6 6.6 0 0 1 0-4.2V7.1H2.3a11 11 0 0 0 0 9.8l3.6-2.8Z" />
        <path fill="#EA4335" d="M12 5.4c1.6 0 3 .6 4.1 1.6l3.1-3.1A11 11 0 0 0 2.3 7.1l3.6 2.8C6.8 7.3 9.2 5.4 12 5.4Z" />
      </svg>
      {children}
    </a>
  )
}

export function EmailDivider() {
  return (
    <div className="flex items-center gap-3 text-xs text-subtle-foreground">
      <span className="h-px flex-1 bg-border" />o con tu email
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}

export function FieldLabel({ htmlFor, children }: { htmlFor: string; children: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="text-[13px] font-medium text-muted-foreground">
      {children}
    </label>
  )
}

export function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (message === undefined) return null
  return (
    <span id={id} className="text-[13px] text-destructive">
      {message}
    </span>
  )
}

type InputProps = ComponentProps<'input'> & { errorId?: string; hasError?: boolean }

export function TextInput({ errorId, hasError = false, className, ...props }: InputProps) {
  return (
    <input
      {...props}
      aria-invalid={hasError}
      aria-describedby={hasError ? errorId : undefined}
      className={cn(inputClass, className)}
    />
  )
}

export function PasswordInput(props: InputProps) {
  const [isVisible, setIsVisible] = useState(false)
  return (
    <div className="relative">
      <TextInput {...props} type={isVisible ? 'text' : 'password'} className="pr-[52px]" />
      <button
        type="button"
        aria-label={isVisible ? 'Ocultar contraseña' : 'Mostrar contraseña'}
        onClick={() => setIsVisible((visible) => !visible)}
        className="absolute top-0.5 right-0.5 grid size-11 place-items-center text-subtle-foreground"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      </button>
    </div>
  )
}

export function PasswordLength({ length }: { length: number }) {
  return (
    <span className="text-xs text-subtle-foreground tabular-nums">
      {length} / {PASSWORD_MIN_LENGTH}
    </span>
  )
}

const alertTones = {
  error: 'border-loss/35 bg-loss/10',
  warn: 'border-warn/30 bg-warn/10',
} as const

export function FormAlert({ tone, children }: { tone: keyof typeof alertTones; children: ReactNode }) {
  return (
    <div role="alert" className={cn('rounded-xl border px-3.5 py-3 text-sm leading-[1.45]', alertTones[tone])}>
      {children}
    </div>
  )
}
