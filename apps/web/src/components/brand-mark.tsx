export function BrandMark({ size = 40, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" aria-hidden="true" className={className}>
      <rect width="30" height="30" rx="8" fill="var(--primary)" />
      <path
        d="M7 20 L12.5 14.5 L16 18 L23 10"
        fill="none"
        stroke="var(--primary-foreground)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
