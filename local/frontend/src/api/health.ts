import { useQuery } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet } from './http'

export type BackendHealthResponse = components['schemas']['HealthResponse']
export function getBackendHealth() { return apiGet<BackendHealthResponse>('/api/v1/health') }
export function useBackendHealth() { return useQuery({ queryKey: ['backend-health'], queryFn: getBackendHealth, retry: 1, refetchInterval: 30_000, refetchOnWindowFocus: true }) }
