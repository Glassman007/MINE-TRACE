import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { ApiError, apiGet, apiPost } from './http'
import { incidentKeys } from './incidents'

export type HandoverItem = components['schemas']['HandoverItemOutput']
export type HandoverPacket = components['schemas']['HandoverPacketResponse']

export interface AcknowledgeHandoverInput {
  packetId: string
  incidentIds: string[]
}

export const handoverKeys = {
  all: ['handovers'] as const,
  detail: (packetId: string) => ['handovers', 'detail', packetId] as const,
}

export function createHandover() { return apiPost<HandoverPacket>('/api/v1/handovers') }
export function getHandover(packetId: string) { return apiGet<HandoverPacket>(`/api/v1/handovers/${encodeURIComponent(packetId)}`) }
export function acknowledgeHandover(packetId: string) { return apiPost<HandoverPacket>(`/api/v1/handovers/${encodeURIComponent(packetId)}/acknowledge`) }

export function useHandover(packetId: string, enabled = true) {
  return useQuery({ queryKey: handoverKeys.detail(packetId), queryFn: () => getHandover(packetId), enabled: enabled && packetId.length > 0 })
}

export function useCreateHandover() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: createHandover, onSuccess: (packet) => queryClient.setQueryData(handoverKeys.detail(packet.id), packet) })
}

export function useAcknowledgeHandover() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: AcknowledgeHandoverInput) => acknowledgeHandover(input.packetId),
    onSuccess: (_packet, input) => {
      void queryClient.invalidateQueries({ queryKey: handoverKeys.detail(input.packetId) })
      void queryClient.invalidateQueries({ queryKey: incidentKeys.all })
      for (const incidentId of input.incidentIds) void queryClient.invalidateQueries({ queryKey: incidentKeys.audit(incidentId) })
    },
    onError: (error, input) => {
      if (error instanceof ApiError && error.status === 409 && error.code === 'HANDOVER_ALREADY_ACKNOWLEDGED') {
        void queryClient.invalidateQueries({ queryKey: handoverKeys.detail(input.packetId) })
      }
    },
  })
}
