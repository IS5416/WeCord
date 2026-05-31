import { useQuery } from '@tanstack/react-query'
import { getAISettings } from '@/api'

export function useAISettings() {
  return useQuery({
    queryKey: ['aiSettings'],
    queryFn: getAISettings,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}
