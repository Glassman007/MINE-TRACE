import { useQuery } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet } from './http'

export type OverviewResponse = components['schemas']['OverviewResponse']

export const overviewQueryKey = ['overview'] as const

export function getOverview() {
  return apiGet<OverviewResponse>('/api/v1/overview')
}

export function useOverview() {
  return useQuery({ queryKey: overviewQueryKey, queryFn: getOverview })
}
