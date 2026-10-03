import { useQuery } from '@tanstack/react-query'
import { apiGet } from './http'
import type { FleetOverviewResponse } from './generated/types'

export type OverviewResponse = FleetOverviewResponse
export const overviewQueryKey = ['fleet-overview'] as const

export function getOverview() {
  return apiGet<FleetOverviewResponse>('/api/v1/fleet/overview')
}

export function useOverview() {
  return useQuery({ queryKey: overviewQueryKey, queryFn: getOverview })
}
