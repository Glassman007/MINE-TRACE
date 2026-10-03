import { useQuery } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet } from './http'

export type MachineSummary = components['schemas']['MachineResponse']
export type ComponentSummary = components['schemas']['ComponentResponse']
export type ContextDimension = components['schemas']['ContextDimensionInput']
export type EvidenceContextSnapshot = components['schemas']['ContextSnapshotInput']
export type EvidenceAttachment = components['schemas']['EvidenceAttachmentOutput']
export type TimelineTransportEvent = components['schemas']['TimelineEvidenceItem']
export type MachineTimelineResponse = components['schemas']['MachineTimelineResponse']

// Presentation adapter only. The transport shape remains generated above.
export type TimelineEvent = Omit<TimelineTransportEvent, 'evidence_id' | 'context_snapshots'> & {
  id: string
  context_snapshots: EvidenceContextSnapshot[]
}

export interface MachineTimelineParams {
  component_id?: string
  from?: string
  to?: string
}

export const machineKeys = {
  all: ['machines'] as const,
  current: ['machines', 'current'] as const,
  currentComponents: ['machines', 'current', 'components'] as const,
  timeline: (machineId: string, params: MachineTimelineParams) => ['machines', 'timeline', machineId, params] as const,
}

export function buildQueryString(params: object) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if ((typeof value === 'string' || typeof value === 'number') && value !== '') search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

export function getCurrentMachine() {
  return apiGet<MachineSummary>('/api/v1/machines/current')
}

export async function getCurrentMachineComponents() {
  const response = await apiGet<components['schemas']['MachineComponentsResponse']>('/api/v1/machines/current/components')
  return response.components
}

export async function getMachineTimeline(machineId: string, params: MachineTimelineParams = {}) {
  const response = await apiGet<MachineTimelineResponse>(
    `/api/v1/machines/${encodeURIComponent(machineId)}/timeline${buildQueryString(params)}`,
  )
  return response.evidence.map<TimelineEvent>((event) => ({
    ...event,
    id: event.evidence_id,
    context_snapshots: event.context_snapshots.map((snapshot) => snapshot.context),
  }))
}

export function useCurrentMachine() {
  return useQuery({ queryKey: machineKeys.current, queryFn: getCurrentMachine })
}

export function useCurrentMachineComponents() {
  return useQuery({ queryKey: machineKeys.currentComponents, queryFn: getCurrentMachineComponents })
}

export function useMachineTimeline(machineId: string, params: MachineTimelineParams = {}, enabled = true) {
  return useQuery({ queryKey: machineKeys.timeline(machineId, params), queryFn: () => getMachineTimeline(machineId, params), enabled: enabled && machineId.length > 0 })
}
