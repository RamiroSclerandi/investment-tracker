import { Link, useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { getAuthStatus, refreshSessionOutcome } from '@/features/auth/session'

const GOOGLE_START_URL = '/api/v1/auth/google/start'

type Phase = 'connecting' | 'failed' | 'unreachable'

export function AuthCompletePage() {
  const navigate = useNavigate()
  const hash = useLocation({ select: (location) => location.hash })
  const [phase, setPhase] = useState<Phase>(() =>
    new URLSearchParams(hash).has('error') ? 'failed' : 'connecting',
  )

  useEffect(() => {
    if (hash) void navigate({ to: '/auth/complete', replace: true })
  }, [hash, navigate])

  useEffect(() => {
    if (phase !== 'connecting') return
    let isCurrent = true
    void refreshSessionOutcome().then((outcome) => {
      if (!isCurrent) return
      const isSignedIn =
        outcome === 'refreshed' || (outcome === 'superseded' && getAuthStatus() === 'authenticated')
      if (isSignedIn) void navigate({ to: '/', replace: true })
      else setPhase(outcome === 'unavailable' ? 'unreachable' : 'failed')
    })
    return () => {
      isCurrent = false
    }
  }, [phase, navigate])

  if (phase === 'connecting') return <ConnectingState />
  if (phase === 'unreachable') return <UnreachableState onRetry={() => setPhase('connecting')} />
  return <GoogleErrorState />
}

function UnreachableState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-[22px]">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">No pudimos conectar</h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          Revisá tu conexión y volvé a intentarlo.
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="h-[52px] rounded-[14px] bg-primary text-base font-semibold text-primary-foreground"
      >
        Reintentar
      </button>
    </div>
  )
}

function ConnectingState() {
  return (
    <div role="status" className="flex items-center justify-center gap-3 py-12">
      <span className="size-5 animate-spin rounded-full border-2 border-border-strong border-t-primary" />
      <span className="text-sm text-muted-foreground">Conectando con Google…</span>
    </div>
  )
}

function GoogleErrorState() {
  return (
    <div className="flex flex-col gap-[22px]">
      <span className="grid size-[72px] place-items-center rounded-[22px] bg-loss/12">
        <svg
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          className="text-loss"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v6M12 16.5h.01" />
        </svg>
      </span>
      <div className="flex flex-col gap-2.5">
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">
          No pudimos completar el ingreso con Google
        </h1>
        <p className="text-[15px] leading-[1.55] text-muted-foreground">
          La solicitud venció o se canceló. Volvé a intentarlo desde el principio.
        </p>
      </div>
      <div className="flex flex-col gap-2.5">
        <a
          href={GOOGLE_START_URL}
          className="grid h-[52px] place-items-center rounded-[14px] bg-primary text-base font-semibold text-primary-foreground"
        >
          Intentar de nuevo
        </a>
        <Link
          to="/login"
          className="grid h-12 place-items-center rounded-lg border border-border-strong text-[15px] font-medium"
        >
          Ingresar con email
        </Link>
      </div>
    </div>
  )
}
