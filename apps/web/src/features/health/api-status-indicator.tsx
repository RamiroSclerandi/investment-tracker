import { cn } from '@/lib/utils'
import type { ApiHealth } from '@/features/health/use-api-health'

const LABELS: Record<ApiHealth, string> = {
  checking: 'Checking API',
  online: 'API online',
  offline: 'API offline',
}

const DOT_CLASSES: Record<ApiHealth, string> = {
  checking: 'bg-muted-foreground animate-pulse',
  online: 'bg-emerald-500',
  offline: 'bg-destructive',
}

export function ApiStatusIndicator({ status }: { status: ApiHealth }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <span aria-hidden="true" className={cn('size-2 rounded-full', DOT_CLASSES[status])} />
      {LABELS[status]}
    </p>
  )
}
