import { useQuery } from '@tanstack/react-query'
import { apiGet } from './http'
import type {
  FleetIncidentCollectionResponse,
  FleetIncidentItem,
  IncidentAuditOutput,
  IncidentAuditResponse,
  IncidentDetailResponse,
  IncidentEvidenceItem,
  IncidentEvidenceResponse,
  IncidentMaintenanceActionsResponse,
  VerificationRunResponse,
  VerificationRunsResponse,
} from './generated/types'
import { buildQueryString } from './machines'

export type IncidentSummary = FleetIncidentItem
export type IncidentDetail = IncidentDetailResponse
export type IncidentEvidenceAssociation = IncidentEvidenceItem
export type IncidentAuditEvent = IncidentAuditOutput
export type VerificationRun = VerificationRunResponse

export interface IncidentCollectionParams {
  offset?: number
  limit?: number
  machine?: string
  component?: string
  start?: string
  end?: string
  status?: string
  state?: string
  model?: string
  site?: string
}

export const incidentKeys = {
  all: ['incidents'] as const,
  list: (params: IncidentCollectionParams) => ['incidents', 'list', params] as const,
  detail: (incidentId: string) => ['incidents', 'detail', incidentId] as const,
  evidence: (incidentId: string) => ['incidents', 'evidence', incidentId] as const,
  audit: (incidentId: string) => ['incidents', 'audit', incidentId] as const,
  verifications: (incidentId: string) => ['incidents', 'verifications', incidentId] as const,
  verificationRun: (runId: string) => ['incidents', 'verification-run', runId] as const,
  maintenance: (incidentId: string) => ['incidents', 'maintenance', incidentId] as const,
}

export function buildIncidentQueryString(params: IncidentCollectionParams) {
  return buildQueryString(params)
}

export function getIncidents(params: IncidentCollectionParams = {}) {
  return apiGet<FleetIncidentCollectionResponse>(`/api/v1/incidents${buildIncidentQueryString(params)}`)
}

export function getIncident(incidentId: string) {
  return apiGet<IncidentDetailResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}`)
}

export async function getIncidentEvidence(incidentId: string) {
  return (await apiGet<IncidentEvidenceResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/evidence`)).evidence
}
export async function getIncidentAudit(incidentId: string) {
  return (await apiGet<IncidentAuditResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/audit`)).audit_events
}
export async function getIncidentVerifications(incidentId: string) {
  return (await apiGet<VerificationRunsResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/verifications`)).runs
}
export function getVerificationRun(runId: string) {
  return apiGet<VerificationRunResponse>(`/api/v1/verifications/${encodeURIComponent(runId)}`)
}
export async function getIncidentMaintenanceActions(incidentId: string) {
  return (await apiGet<IncidentMaintenanceActionsResponse>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/maintenance-actions`)).actions
}

export function useIncidents(params: IncidentCollectionParams = {}) { return useQuery({ queryKey: incidentKeys.list(params), queryFn: () => getIncidents(params) }) }
export function useIncident(incidentId: string, enabled = true) { return useQuery({ queryKey: incidentKeys.detail(incidentId), queryFn: () => getIncident(incidentId), enabled: enabled && incidentId.length > 0 }) }
export function useIncidentEvidence(incidentId: string, enabled = true) { return useQuery({ queryKey: incidentKeys.evidence(incidentId), queryFn: () => getIncidentEvidence(incidentId), enabled: enabled && incidentId.length > 0 }) }
export function useIncidentAudit(incidentId: string, enabled = true) { return useQuery({ queryKey: incidentKeys.audit(incidentId), queryFn: () => getIncidentAudit(incidentId), enabled: enabled && incidentId.length > 0 }) }
export function useIncidentVerifications(incidentId: string, enabled = true) { return useQuery({ queryKey: incidentKeys.verifications(incidentId), queryFn: () => getIncidentVerifications(incidentId), enabled: enabled && incidentId.length > 0 }) }
export function useVerificationRun(runId: string, enabled = true) { return useQuery({ queryKey: incidentKeys.verificationRun(runId), queryFn: () => getVerificationRun(runId), enabled: enabled && runId.length > 0 }) }
export function useIncidentMaintenanceActions(incidentId: string, enabled = true) { return useQuery({ queryKey: incidentKeys.maintenance(incidentId), queryFn: () => getIncidentMaintenanceActions(incidentId), enabled: enabled && incidentId.length > 0 }) }
