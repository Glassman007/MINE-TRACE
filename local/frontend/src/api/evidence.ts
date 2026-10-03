import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiPost } from './http'
import { incidentKeys } from './incidents'
import { machineKeys } from './machines'
import { overviewQueryKey } from './overview'

export type EvidenceMode = 'machine-event' | 'maintenance-record' | 'human-observation'
export type ContextQuality = components['schemas']['ContextQuality']
export type ContextDimensionInput = components['schemas']['ContextDimensionInput']
export type ContextSnapshotInput = components['schemas']['ContextSnapshotInput']
export type AttachmentMetadataInput = components['schemas']['EvidenceAttachmentInput']
export type MachineEventInput = components['schemas']['MachineEventInput']
export type MaintenanceRecordInput = components['schemas']['MaintenanceRecordInput']
export type HumanObservationInput = components['schemas']['HumanObservationInput']
export type EvidenceIngestionInput = MachineEventInput | MaintenanceRecordInput | HumanObservationInput
export type EvidenceIngestionResponse = components['schemas']['EvidenceIngestionResponse']

export interface IngestEvidenceVariables {
  mode: EvidenceMode
  input: EvidenceIngestionInput
}

function endpointForMode(mode: EvidenceMode) {
  switch (mode) {
    case 'machine-event': return '/api/v1/evidence/machine-events'
    case 'maintenance-record': return '/api/v1/evidence/maintenance-records'
    case 'human-observation': return '/api/v1/evidence/human-observations'
  }
}

export function ingestEvidence({ mode, input }: IngestEvidenceVariables) {
  return apiPost<EvidenceIngestionResponse, EvidenceIngestionInput>(endpointForMode(mode), input)
}

export function useIngestEvidence() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ingestEvidence,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: overviewQueryKey })
      void queryClient.invalidateQueries({ queryKey: incidentKeys.all })
      void queryClient.invalidateQueries({ queryKey: machineKeys.timeline(variables.input.machine_id, {}) })
      void queryClient.invalidateQueries({ queryKey: machineKeys.current })
    },
  })
}
