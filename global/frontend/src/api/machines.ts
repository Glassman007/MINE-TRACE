import { useQuery } from '@tanstack/react-query'
import { apiGet } from './http'
import type {
  ComponentResponse,
  FleetIncidentCollectionResponse,
  FleetMachineCollectionResponse,
  FleetMachineItem,
  MachineComponentsResponse,
  MachineSessionsResponse,
} from './generated/types'

export type MachineSummary = FleetMachineItem
export type MachineCollectionResponse = FleetMachineCollectionResponse
export type ComponentSummary = ComponentResponse

export interface MachineCollectionParams {
  offset?: number
  limit?: number
  search?: string
  site?: string
  machine_type?: string
  model?: string
}

export interface PageParams { offset?: number; limit?: number }

export const machineKeys = {
  all: ['machines'] as const,
  list: (params: MachineCollectionParams) => ['machines', 'list', params] as const,
  detail: (machineId: string) => ['machines', 'detail', machineId] as const,
  components: (machineId: string) => ['machines', 'components', machineId] as const,
  sessions: (machineId: string, params: PageParams) => ['machines', 'sessions', machineId, params] as const,
  incidents: (machineId: string, params: PageParams) => ['machines', 'incidents', machineId, params] as const,
}

export function buildQueryString<T extends object>(params: T) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if ((typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') && value !== '') {
      search.set(key, String(value))
    }
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

export function getMachines(params: MachineCollectionParams = {}) {
  return apiGet<FleetMachineCollectionResponse>(`/api/v1/machines${buildQueryString(params)}`)
}

export function getMachine(machineId: string) {
  return apiGet<FleetMachineItem>(`/api/v1/machines/${encodeURIComponent(machineId)}`)
}

export async function getMachineComponents(machineId: string) {
  const response = await apiGet<MachineComponentsResponse>(`/api/v1/machines/${encodeURIComponent(machineId)}/components`)
  return response.components
}

export function getMachineSessions(machineId: string, params: PageParams = {}) {
  return apiGet<MachineSessionsResponse>(`/api/v1/machines/${encodeURIComponent(machineId)}/sessions${buildQueryString(params)}`)
}

export function getMachineIncidents(machineId: string, params: PageParams = {}) {
  return apiGet<FleetIncidentCollectionResponse>(`/api/v1/machines/${encodeURIComponent(machineId)}/incidents${buildQueryString(params)}`)
}

export function useMachines(params: MachineCollectionParams = {}) {
  return useQuery({ queryKey: machineKeys.list(params), queryFn: () => getMachines(params) })
}
export function useMachine(machineId: string, enabled = true) {
  return useQuery({ queryKey: machineKeys.detail(machineId), queryFn: () => getMachine(machineId), enabled: enabled && machineId.length > 0 })
}
export function useMachineComponents(machineId: string, enabled = true) {
  return useQuery({ queryKey: machineKeys.components(machineId), queryFn: () => getMachineComponents(machineId), enabled: enabled && machineId.length > 0 })
}
export function useMachineSessions(machineId: string, params: PageParams = {}, enabled = true) {
  return useQuery({ queryKey: machineKeys.sessions(machineId, params), queryFn: () => getMachineSessions(machineId, params), enabled: enabled && machineId.length > 0 })
}
export function useMachineIncidents(machineId: string, params: PageParams = {}, enabled = true) {
  return useQuery({ queryKey: machineKeys.incidents(machineId, params), queryFn: () => getMachineIncidents(machineId, params), enabled: enabled && machineId.length > 0 })
}
