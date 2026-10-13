import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/api/client'

export type ApiHealth = 'checking' | 'online' | 'offline'

const REFETCH_INTERVAL_MS = 30_000

export function useApiHealth(): ApiHealth {
  const { isSuccess, isError } = useQuery({
    queryKey: ['api', 'health'],
    queryFn: async () => {
      const { response } = await apiClient.GET('/api/v1/healthz')
      if (!response.ok) throw new Error(`Health check failed with status ${response.status}`)
      return true
    },
    retry: false,
    refetchInterval: REFETCH_INTERVAL_MS,
  })

  if (isSuccess) return 'online'
  return isError ? 'offline' : 'checking'
}
