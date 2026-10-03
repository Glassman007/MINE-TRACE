// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentDetailPage } from './IncidentDetailPage'

function response(body: unknown, status = 200) { return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })) }

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/incidents/incident-01']}><Routes><Route path="/incidents/:incidentId" element={<IncidentDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('IncidentDetailPage global read-only chain', () => {
  it('shows evidence, maintenance, verification and provenance without local authority actions', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/incidents/incident-01') return response({ incident_id: 'incident-01', machine_id: 'machine-01', status: 'OPEN', owner_ref: null, severity: 'HIGH', due_state: null, due_time: null, created_at: '2026-10-03T07:00:00Z', updated_at: '2026-10-03T08:00:00Z', audit_events: [] })
      if (url === '/api/v1/incidents/incident-01/evidence') return response({ incident_id: 'incident-01', evidence: [{ link_id: 'link-01', evidence_id: 'evidence-01', machine_id: 'machine-01', component_id: null, source_type: 'HUMAN_OBSERVATION', original_source_record_id: 'edge-e-1', original_timestamp: '2026-10-03T07:15:00Z', canonical_event_type: 'OPERATOR_NOTE', canonical_payload: { text: 'Hydraulic whine' }, raw_source_payload: {}, provenance: { source: 'edge' }, relationship_type: 'RELATED', deterministic_rule_identifier: null, link_reason: 'synchronized', linked_at: '2026-10-03T07:20:00Z', is_active: true, unlinked_at: null }] })
      if (url === '/api/v1/incidents/incident-01/maintenance-actions') return response({ incident_id: 'incident-01', actions: [{ action_id: 'action-01', machine_id: 'machine-01', incident_id: 'incident-01', session_id: 'session-01', component_id: null, action_type: 'INSPECTION', description: 'Inspected hydraulic pump', original_timestamp: '2026-10-03T07:30:00Z', ingestion_timestamp: '2026-10-03T08:00:00Z', source_report_revision: 2, provenance: { source: 'edge-maintenance' } }] })
      if (url === '/api/v1/incidents/incident-01/audit') return response({ incident_id: 'incident-01', audit_events: [{ id: 'audit-01', action: 'EVIDENCE_LINKED', occurred_at: '2026-10-03T07:20:00Z', payload: { source: 'sync' } }] })
      if (url === '/api/v1/incidents/incident-01/verifications') return response({ incident_id: 'incident-01', runs: [{ id: 'verification-01', incident_id: 'incident-01', session_id: 'session-01', rule_identifier: 'edge.rule', rule_name: null, rule_type: null, window_minutes: null, window_ends_at: null, started_at: '2026-10-03T07:40:00Z', completed_at: null, result: null, outcome_payload: {}, created_at: '2026-10-03T08:00:00Z' }] })
      if (url === '/api/v1/machines/machine-01') return response({ id: 'machine-01', display_name: 'Haul Truck 01', asset_code: 'HT-01', machine_type: 'HAUL_TRUCK', manufacturer: null, model: null, site_name: null, site_area: null, latest_sync_received_at: null, latest_acknowledged_at: null, latest_acknowledgement_status: null, latest_report_revision: null })
      return response({ error: { code: 'NOT_FOUND', message: `Unexpected ${url}` } }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDetail()

    expect(await screen.findByText('Canonical incident')).toBeInTheDocument()
    expect(await screen.findByText('OPERATOR_NOTE')).toBeInTheDocument()
    expect(await screen.findByText('INSPECTION')).toBeInTheDocument()
    expect(screen.getByText('Verification history')).toBeInTheDocument()
    expect(screen.getByText('Provenance and audit')).toBeInTheDocument()
    for (const label of [/add evidence/i, /move evidence/i, /split incident/i, /start verification/i, /evaluate verification/i, /return to service/i]) {
      expect(screen.queryByRole('button', { name: label })).not.toBeInTheDocument()
    }
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })
})
