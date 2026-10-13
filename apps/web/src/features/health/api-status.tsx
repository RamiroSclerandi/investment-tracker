import { ApiStatusIndicator } from '@/features/health/api-status-indicator'
import { useApiHealth } from '@/features/health/use-api-health'

export function ApiStatus() {
  return <ApiStatusIndicator status={useApiHealth()} />
}
