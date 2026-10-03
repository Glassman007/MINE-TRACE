import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet, apiPost } from './http'
import { overviewQueryKey } from './overview'
import { evidenceBundleKeys } from './evidenceBundle'

export type IncidentSummaryTransport = components['schemas']['IncidentSummaryResponse']
export type IncidentDetailTransport = components['schemas']['IncidentDetailResponse']
export type IncidentEvidenceAssociation = components['schemas']['IncidentEvidenceItem']
export type IncidentAuditEvent = components['schemas']['IncidentAuditOutput']
export type VerificationRun = components['schemas']['VerificationRunResponse']
export type CorrectionResponse = components['schemas']['MoveEvidenceResponse'] | components['schemas']['SplitIncidentResponse']
export type EvaluateDueResponse = components['schemas']['DueVerificationEvaluationResponse']

// UI view models only; transport contracts remain generated above.
export type IncidentSummary = Omit<IncidentSummaryTransport, 'incident_id'> & { id: string }
export type IncidentDetail = Omit<IncidentDetailTransport, 'incident_id'> & { id: string }

export interface IncidentCollectionParams {
  offset?: number
  limit?: number
  machine_id?: string
  status?: string
  severity?: string
  owner_ref?: string
  due_state?: string
}

export interface MoveEvidenceRequest {
  sourceIncidentId: string
  evidenceId: string
  targetIncidentId: string
  reason: string
}

export interface SplitIncidentRequest {
  sourceIncidentId: string
  evidenceIds: string[]
  reason: string
}

export const incidentKeys = {
  all: ['incidents'] as const,
  list: (params: IncidentCollectionParams) => ['incidents', 'list', params] as const,
  detail: (incidentId: string) => ['incidents', 'detail', incidentId] as const,
  evidence: (incidentId: string) => ['incidents', 'evidence', incidentId] as const,
  audit: (incidentId: string) => ['incidents', 'audit', incidentId] as const,
  verifications: (incidentId: string) => ['incidents', 'verifications', incidentId] as const,
  verificationRun: (runId: string) => ['incidents', 'verification-run', runId] as const,
  allForMachine: (machineId: string) => ['incidents', 'all-for-machine', machineId] as const,
}

export function buildIncidentQueryString(params: IncidentCollectionParams) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

function summaryView(item: IncidentSummaryTransport): IncidentSummary {
  const { incident_id, ...rest } = item
  return { ...rest, id: incident_id }
}

function detailView(item: IncidentDetailTransport): IncidentDetail {
  const { incident_id, ...rest } = item
  return { ...rest, id: incident_id }
}

export async function getIncidents(params: IncidentCollectionParams = {}) {
  const payload = await apiGet<components['schemas']['IncidentCollectionResponse']>(`/api/v1/incidents${buildIncidentQueryString(params)}`)
  return { ...payload, items: payload.items.map(summaryView) }
}

export async function getAllIncidentsForMachine(machineId: string) {
  const limit = 200
  let offset = 0
  const items: IncidentSummary[] = []

  while (true) {
    const page = await getIncidents({ machine_id: machineId, offset, limit })
    items.push(...page.items)
    offset += page.items.length
    if (offset >= page.total || page.items.length === 0) break
  }

  return items
}

export async function getIncident(incidentId: string) {
  return detailView(await apiGet<IncidentDetailTransport>(`/api/v1/incidents/${encodeURIComponent(incidentId)}`))
}

export async function getIncidentEvidence(incidentId: string) {
  const payload = await apiGet<components['schemas']['IncidentEvidenceResponse']>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/evidence`)
  return payload.evidence
}

export async function getIncidentAudit(incidentId: string) {
  const payload = await apiGet<components['schemas']['IncidentAuditResponse']>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/audit`)
  return payload.audit_events
}

export async function getIncidentVerifications(incidentId: string) {
  const payload = await apiGet<components['schemas']['VerificationRunsResponse']>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/verifications`)
  return payload.runs
}

export function getVerificationRun(runId: string) {
  return apiGet<VerificationRun>(`/api/v1/verifications/${encodeURIComponent(runId)}`)
}

export function moveIncidentEvidence(input: MoveEvidenceRequest) {
  return apiPost<components['schemas']['MoveEvidenceResponse'], components['schemas']['MoveEvidenceRequest']>(
    `/api/v1/incidents/${encodeURIComponent(input.sourceIncidentId)}/evidence/${encodeURIComponent(input.evidenceId)}/move`,
    { target_incident_id: input.targetIncidentId, reason: input.reason },
  )
}

export function splitIncident(input: SplitIncidentRequest) {
  return apiPost<components['schemas']['SplitIncidentResponse'], components['schemas']['SplitIncidentRequest']>(
    `/api/v1/incidents/${encodeURIComponent(input.sourceIncidentId)}/split`,
    { evidence_ids: input.evidenceIds, reason: input.reason },
  )
}

export function startIncidentVerification(incidentId: string) {
  return apiPost<VerificationRun>(`/api/v1/incidents/${encodeURIComponent(incidentId)}/verification`)
}

export function evaluateDueVerifications() {
  return apiPost<EvaluateDueResponse>('/api/v1/verifications/evaluate-due')
}

function invalidateAuthoritativeIncidentState(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: incidentKeys.all })
  void queryClient.invalidateQueries({ queryKey: overviewQueryKey })
}

export function useIncidents(params: IncidentCollectionParams = {}, enabled = true) {
  return useQuery({ queryKey: incidentKeys.list(params), queryFn: () => getIncidents(params), enabled })
}

export function useAllMachineIncidents(machineId: string, enabled = true) {
  return useQuery({
    queryKey: incidentKeys.allForMachine(machineId),
    queryFn: () => getAllIncidentsForMachine(machineId),
    enabled: enabled && machineId.length > 0,
  })
}

export function useIncident(incidentId: string, enabled = true) {
  return useQuery({ queryKey: incidentKeys.detail(incidentId), queryFn: () => getIncident(incidentId), enabled: enabled && incidentId.length > 0 })
}

export function useIncidentEvidence(incidentId: string, enabled = true) {
  return useQuery({ queryKey: incidentKeys.evidence(incidentId), queryFn: () => getIncidentEvidence(incidentId), enabled: enabled && incidentId.length > 0 })
}

export function useIncidentAudit(incidentId: string, enabled = true) {
  return useQuery({ queryKey: incidentKeys.audit(incidentId), queryFn: () => getIncidentAudit(incidentId), enabled: enabled && incidentId.length > 0 })
}

export function useIncidentVerifications(incidentId: string, enabled = true) {
  return useQuery({ queryKey: incidentKeys.verifications(incidentId), queryFn: () => getIncidentVerifications(incidentId), enabled: enabled && incidentId.length > 0 })
}

export function useVerificationRun(runId: string, enabled = true) {
  return useQuery({ queryKey: incidentKeys.verificationRun(runId), queryFn: () => getVerificationRun(runId), enabled: enabled && runId.length > 0 })
}

export function useMoveIncidentEvidence() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: moveIncidentEvidence,
    onSuccess: (_data, variables) => {
      invalidateAuthoritativeIncidentState(queryClient)
      for (const incidentId of [variables.sourceIncidentId, variables.targetIncidentId]) {
        void queryClient.invalidateQueries({ queryKey: incidentKeys.detail(incidentId) })
        void queryClient.invalidateQueries({ queryKey: incidentKeys.evidence(incidentId) })
        void queryClient.invalidateQueries({ queryKey: incidentKeys.audit(incidentId) })
        void queryClient.invalidateQueries({ queryKey: evidenceBundleKeys.detail(incidentId) })
      }
    },
  })
}

export function useSplitIncident() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: splitIncident,
    onSuccess: (_data, variables) => {
      invalidateAuthoritativeIncidentState(queryClient)
      void queryClient.invalidateQueries({ queryKey: incidentKeys.detail(variables.sourceIncidentId) })
      void queryClient.invalidateQueries({ queryKey: incidentKeys.evidence(variables.sourceIncidentId) })
      void queryClient.invalidateQueries({ queryKey: incidentKeys.audit(variables.sourceIncidentId) })
      void queryClient.invalidateQueries({ queryKey: evidenceBundleKeys.detail(variables.sourceIncidentId) })
    },
  })
}

export function useStartIncidentVerification() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (incidentId: string) => startIncidentVerification(incidentId),
    onSuccess: (_data, incidentId) => {
      invalidateAuthoritativeIncidentState(queryClient)
      void queryClient.invalidateQueries({ queryKey: incidentKeys.detail(incidentId) })
      void queryClient.invalidateQueries({ queryKey: incidentKeys.verifications(incidentId) })
      void queryClient.invalidateQueries({ queryKey: incidentKeys.audit(incidentId) })
      void queryClient.invalidateQueries({ queryKey: evidenceBundleKeys.detail(incidentId) })
    },
  })
}

export function useEvaluateDueVerifications() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: evaluateDueVerifications, onSuccess: () => invalidateAuthoritativeIncidentState(queryClient) })
}
