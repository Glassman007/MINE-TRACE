import { useQuery } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet } from './http'

export type SyncStatusResponse = components['schemas']['SyncStatusResponse']
export const syncStatusKey = ['sync', 'status'] as const
export function getSyncStatus() { return apiGet<SyncStatusResponse>('/api/v1/sync/status') }
export function useSyncStatus() { return useQuery({ queryKey: syncStatusKey, queryFn: getSyncStatus, refetchInterval: 30_000 }) }
