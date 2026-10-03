import { useQuery } from '@tanstack/react-query'
import { apiGet } from './http'
import { buildQueryString } from './machines'
import type { MaintenanceQueueResponse } from './generated/types'

export function getMaintenanceQueue(params: { offset?: number; limit?: number } = {}) {
  return apiGet<MaintenanceQueueResponse>(`/api/v1/maintenance-queue${buildQueryString(params)}`)
}
export function useMaintenanceQueue(params: { offset?: number; limit?: number } = {}) {
  return useQuery({ queryKey: ['maintenance-queue', params], queryFn: () => getMaintenanceQueue(params) })
}
