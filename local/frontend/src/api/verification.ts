import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet, apiPost } from './http'
import { incidentKeys } from './incidents'
import { overviewQueryKey } from './overview'

export type VerificationRunResponse = components['schemas']['VerificationRunResponse']

export async function getIncidentVerifications(incidentId: string) {
  const payload = await apiGet<components['schemas']['VerificationRunsResponse']>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/verifications`)
  return payload.runs
}

export function getVerification(runId: string) {
  return apiGet<VerificationRunResponse>(`/api/v1/verifications/${encodeURIComponent(runId)}`)
}

export function startVerification(incidentId: string) {
  return apiPost<VerificationRunResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/verification`)
}

export function evaluateDueVerifications() {
  return apiPost<components['schemas']['DueVerificationEvaluationResponse']>('/api/v1/verifications/evaluate-due')
}

export function useVerification(runId: string, enabled = true) {
  return useQuery({ queryKey: incidentKeys.verificationRun(runId), queryFn: () => getVerification(runId), enabled: enabled && runId.length > 0 })
}

export function useIncidentVerifications(incidentId: string) {
  return useQuery({ queryKey: incidentKeys.verifications(incidentId), queryFn: () => getIncidentVerifications(incidentId), enabled: incidentId.length > 0 })
}

export function useStartVerification() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: startVerification,
    onSuccess: (_data, incidentId) => {
      void queryClient.invalidateQueries({ queryKey: incidentKeys.detail(incidentId) })
      void queryClient.invalidateQueries({ queryKey: incidentKeys.verifications(incidentId) })
      void queryClient.invalidateQueries({ queryKey: overviewQueryKey })
    },
  })
}

export function useEvaluateDueVerifications() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: evaluateDueVerifications,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: incidentKeys.all })
      void queryClient.invalidateQueries({ queryKey: overviewQueryKey })
    },
  })
}
