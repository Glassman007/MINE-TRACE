import { useMutation } from '@tanstack/react-query'
import { apiPost } from './http'
import type { FleetAIAnalysisRequest, FleetAIAnalysisResponse } from './generated/types'

export function analyzeFleet(input: FleetAIAnalysisRequest) {
  return apiPost<FleetAIAnalysisResponse, FleetAIAnalysisRequest>('/api/v1/ai/analyze', input)
}

export function useAnalyzeFleet() {
  return useMutation({ mutationFn: analyzeFleet, retry: 0 })
}
