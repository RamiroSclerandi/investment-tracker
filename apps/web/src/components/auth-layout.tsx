import { Outlet } from '@tanstack/react-router'
import { BrandMark } from '@/components/brand-mark'

const CHART_LINE =
  'M0,175 L44,190 L70,148 L114,143 L141,135 L167,110 L220,113 L255,86 L291,62 L326,53 L343,82 L379,63 L414,41 L458,24 L484,22 L520,10'

function BrandPanel() {
  return (
    <aside className="hidden flex-1 flex-col gap-10 border-r border-border bg-[radial-gradient(700px_500px_at_20%_110%,rgb(240_70_216/0.16),transparent_70%),#0e0e13] px-14 py-12 lg:flex">
      <div className="flex items-center gap-2.5">
        <BrandMark size={30} />
        <span className="text-[17px] font-semibold">Investment Tracker</span>
      </div>
      <div className="flex max-w-[520px] flex-1 flex-col justify-center gap-5">
        <p className="text-[44px] leading-[1.08] font-semibold tracking-[-0.03em] text-balance">
          Tu cartera de cripto y mercado argentino, en vivo.
        </p>
        <p className="text-[17px] leading-normal text-muted-foreground">
          Valor total, P&amp;L realizado y no realizado en pesos o dólar MEP, y la evolución de cada activo.
        </p>
        <svg viewBox="0 0 520 200" className="mt-3 h-auto w-full" aria-hidden="true">
          <defs>
            <linearGradient id="brand-chart-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--gain)" stopOpacity=".25" />
              <stop offset="1" stopColor="var(--gain)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${CHART_LINE} L520,200 L0,200 Z`} fill="url(#brand-chart-fill)" />
          <path d={CHART_LINE} fill="none" stroke="var(--gain)" strokeWidth="2.5" strokeLinejoin="round" />
          <circle cx="520" cy="10" r="5" fill="var(--gain)" />
        </svg>
      </div>
    </aside>
  )
}

export function AuthLayout() {
  return (
    <div className="flex min-h-svh bg-background text-foreground">
      <BrandPanel />
      <main className="flex flex-1 justify-center bg-[radial-gradient(400px_300px_at_50%_0%,rgb(240_70_216/0.14),transparent_70%)] px-5 pt-14 pb-8 lg:items-center lg:bg-none lg:px-6 lg:py-12">
        <div className="flex w-full max-w-sm flex-col lg:max-w-[380px]">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
