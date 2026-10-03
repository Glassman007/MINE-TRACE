import { useMutation } from '@tanstack/react-query'
import { apiPost } from './http'
import type { FleetSemanticSearchRequest, FleetSemanticSearchResponse } from './generated/types'

export function searchFleetSemantic(input: FleetSemanticSearchRequest) {
  return apiPost<FleetSemanticSearchResponse, FleetSemanticSearchRequest>('/api/v1/search/semantic', input)
}
export function useFleetSemanticSearch() {
  return useMutation({ mutationFn: searchFleetSemantic, retry: 0 })
}
