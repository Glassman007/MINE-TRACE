import { useMutation } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiPost } from './http'

export type SemanticSearchRequest = components['schemas']['SemanticSearchRequest']
export type SemanticSearchResponse = components['schemas']['SemanticSearchResponse']

export function semanticSearch(input: SemanticSearchRequest) {
  return apiPost<SemanticSearchResponse, SemanticSearchRequest>('/api/v1/semantic-search', input)
}

export function useSemanticSearch() {
  return useMutation({ mutationFn: semanticSearch, retry: 0 })
}
