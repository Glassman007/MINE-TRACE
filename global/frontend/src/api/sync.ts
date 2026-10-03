import { useQuery } from '@tanstack/react-query'
import { apiGet } from './http'
import { buildQueryString } from './machines'
import type { SyncConflictCollectionResponse, SyncHealthResponse } from './generated/types'

export function getSyncHealth(staleAfterHours?: number) {
  return apiGet<SyncHealthResponse>(`/api/v1/sync/health${buildQueryString({ stale_after_hours: staleAfterHours })}`)
}
export function getSyncConflicts(params: { offset?: number; limit?: number; unresolved_only?: boolean } = {}) {
  return apiGet<SyncConflictCollectionResponse>(`/api/v1/sync/conflicts${buildQueryString(params)}`)
}
export function useSyncHealth(staleAfterHours?: number) { return useQuery({ queryKey: ['sync-health', staleAfterHours], queryFn: () => getSyncHealth(staleAfterHours) }) }
export function useSyncConflicts(params: { offset?: number; limit?: number; unresolved_only?: boolean } = {}) { return useQuery({ queryKey: ['sync-conflicts', params], queryFn: () => getSyncConflicts(params) }) }
