import { useQuery } from '@tanstack/react-query'
import { apiGet } from './http'
import type { HealthResponse } from './generated/types'

export type BackendHealthResponse = HealthResponse
export function getBackendHealth() { return apiGet<HealthResponse>('/api/v1/health') }
export function useBackendHealth() { return useQuery({ queryKey: ['backend-health'], queryFn: getBackendHealth, retry: 1, refetchInterval: 30_000, refetchOnWindowFocus: true }) }
