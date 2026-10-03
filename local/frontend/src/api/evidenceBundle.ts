import { useQuery } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet } from './http'

export type EvidenceBundleResponse = components['schemas']['EvidenceBundleResponse']
export type EvidenceBundleStatus = components['schemas']['EvidenceBundleStatus']

export const evidenceBundleKeys = {
  detail: (incidentId: string) => ['incidents', 'evidence-bundle', incidentId] as const,
}

export function getEvidenceBundle(incidentId: string) {
  return apiGet<EvidenceBundleResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/evidence-bundle`)
}

export function useEvidenceBundle(incidentId: string, enabled = true) {
  return useQuery({ queryKey: evidenceBundleKeys.detail(incidentId), queryFn: () => getEvidenceBundle(incidentId), enabled: enabled && incidentId.length > 0 })
}
