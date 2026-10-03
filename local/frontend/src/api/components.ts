import { useQuery } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet } from './http'
import { getCurrentMachineComponents, getMachineTimeline } from './machines'

export type ComponentResponse = components['schemas']['ComponentResponse']

export const componentKeys = {
  all: ['components'] as const,
  current: ['components', 'current-machine'] as const,
  detail: (componentId: string) => ['components', 'detail', componentId] as const,
  timeline: (machineId: string, componentId: string) => ['components', 'timeline', machineId, componentId] as const,
}

export function getComponent(componentId: string) {
  return apiGet<ComponentResponse>(`/api/v1/components/${encodeURIComponent(componentId)}`)
}

export function useComponents() {
  return useQuery({ queryKey: componentKeys.current, queryFn: getCurrentMachineComponents })
}

export function useComponent(componentId: string) {
  return useQuery({ queryKey: componentKeys.detail(componentId), queryFn: () => getComponent(componentId), enabled: componentId.length > 0 })
}

export function useComponentTimeline(machineId: string, componentId: string) {
  return useQuery({
    queryKey: componentKeys.timeline(machineId, componentId),
    queryFn: () => getMachineTimeline(machineId, { component_id: componentId }),
    enabled: machineId.length > 0 && componentId.length > 0,
  })
}
