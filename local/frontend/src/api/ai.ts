import { useMutation } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiPost } from './http'

export type AIAnalysisResponse = components['schemas']['AIAnalysisResult']
export type CitedAIClaim = components['schemas']['AIClaim']

export function analyzeIncidentEvidence(incidentId: string) {
  return apiPost<AIAnalysisResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/ai-analysis`)
}

/** Advisory only: explicit-action mutation; never authoritative cache state. */
export function useAnalyzeIncidentEvidence() {
  return useMutation({ mutationFn: (incidentId: string) => analyzeIncidentEvidence(incidentId), retry: 0 })
}
