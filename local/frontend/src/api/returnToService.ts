import { useQuery } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet } from './http'

export type ReturnToServiceResponse = components['schemas']['ReturnToServiceResponse']
export const returnToServiceKey = ['return-to-service'] as const
export function getReturnToService() { return apiGet<ReturnToServiceResponse>('/api/v1/return-to-service') }
export function useReturnToService() { return useQuery({ queryKey: returnToServiceKey, queryFn: getReturnToService }) }
