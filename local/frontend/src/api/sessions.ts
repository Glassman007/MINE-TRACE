import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import type { components } from './generated/openapi'
import { apiGet, apiPost } from './http'
import { overviewQueryKey } from './overview'
import { syncStatusKey } from './sync'

export type OperatingSession = components['schemas']['OperatingSessionResponse']
export type MachineSessionReport = components['schemas']['MachineSessionReport']

export const sessionKeys = {
  active: ['sessions', 'active'] as const,
  detail: (sessionId: string) => ['sessions', 'detail', sessionId] as const,
  report: (sessionId: string) => ['sessions', 'report', sessionId] as const,
}

export function getActiveSession() { return apiGet<OperatingSession>('/api/v1/sessions/active') }
export function getSession(sessionId: string) { return apiGet<OperatingSession>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`) }
export function getSessionReport(sessionId: string) { return apiGet<MachineSessionReport>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/report`) }
export function openSession(body: components['schemas']['OperatingSessionOpenRequest']) { return apiPost<OperatingSession, components['schemas']['OperatingSessionOpenRequest']>('/api/v1/sessions', body) }
export function closeSession(sessionId: string, body: components['schemas']['OperatingSessionCloseRequest']) { return apiPost<OperatingSession, components['schemas']['OperatingSessionCloseRequest']>(`/api/v1/sessions/${encodeURIComponent(sessionId)}/close`, body) }
export function rolloverSession(body: components['schemas']['OperatingSessionRolloverRequest']) { return apiPost<components['schemas']['OperatingSessionRolloverResponse'], components['schemas']['OperatingSessionRolloverRequest']>('/api/v1/sessions/rollover', body) }

export function useActiveSession() { return useQuery({ queryKey: sessionKeys.active, queryFn: getActiveSession, retry: false }) }
export function useSession(sessionId: string, enabled = true) { return useQuery({ queryKey: sessionKeys.detail(sessionId), queryFn: () => getSession(sessionId), enabled: enabled && sessionId.length > 0 }) }
export function useSessionReport(sessionId: string, enabled = true) { return useQuery({ queryKey: sessionKeys.report(sessionId), queryFn: () => getSessionReport(sessionId), enabled: enabled && sessionId.length > 0 }) }
function invalidateSessionState(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: sessionKeys.active })
  void queryClient.invalidateQueries({ queryKey: overviewQueryKey })
  void queryClient.invalidateQueries({ queryKey: syncStatusKey })
}

export function useOpenSession() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: openSession, onSuccess: () => invalidateSessionState(queryClient) })
}

export function useCloseSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: string; body: components['schemas']['OperatingSessionCloseRequest'] }) => closeSession(sessionId, body),
    onSuccess: (session) => {
      invalidateSessionState(queryClient)
      void queryClient.invalidateQueries({ queryKey: sessionKeys.detail(session.session_id) })
      void queryClient.invalidateQueries({ queryKey: sessionKeys.report(session.session_id) })
    },
  })
}

export function useRolloverSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: rolloverSession,
    onSuccess: (result) => {
      invalidateSessionState(queryClient)
      void queryClient.invalidateQueries({ queryKey: sessionKeys.detail(result.closed_session.session_id) })
      void queryClient.invalidateQueries({ queryKey: sessionKeys.report(result.closed_session.session_id) })
      void queryClient.invalidateQueries({ queryKey: sessionKeys.detail(result.new_session.session_id) })
    },
  })
}
