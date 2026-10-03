// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HistoryPage } from './HistoryPage'
import { SearchPage } from './SearchPage'
import { SessionPage } from './SessionPage'
import { ReturnToServicePage } from './ReturnToServicePage'
import { SyncPage } from './SyncPage'

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}
function renderPage(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>)
}
const machine = { id: 'machine-1', display_name: 'EXC-204', asset_code: 'EXC-204', machine_type: 'Hydraulic Excavator', manufacturer: null, model: null, site_name: 'North Ridge Mine', site_area: null }
const overview = { demo_mode: true, machine, active_session: { session_id: 'session-open', machine_id: machine.id, started_at: '2026-10-03T07:30:00Z', ended_at: null, state: 'OPEN', operating_hours: null, revision: 1, created_at: '2026-10-03T07:30:00Z', updated_at: '2026-10-03T07:30:00Z' }, operating_state: 'OPEN', unresolved_incident_count: 1, counts: { components: 7, evidence: 6, incidents: 2, incidents_by_status: { OPEN: 1, VERIFIED: 1 } }, return_to_service: { state: 'DO_NOT_RETURN', blocking_reasons: [], policy_identifier: 'demo.policy', policy_revision: 1 }, sync: { transport_configured: true, transport_available: true, transport_checked_at: '2026-10-03T07:05:00Z', latest_package_state: 'CONFLICT', last_acknowledgement: '2026-10-03T07:05:00Z', last_error: null } }

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('local workflow pages', () => {
  it('history shows canonical maintenance evidence rather than semantic candidates', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/machines/current') return response(machine)
      if (url.startsWith('/api/v1/machines/machine-1/timeline')) return response({ machine_id: machine.id, component_id: null, from_timestamp: null, to_timestamp: null, evidence: [{ evidence_id: 'e-maint', machine_id: machine.id, component_id: 'pump', source_type: 'MAINTENANCE_RECORD', original_source_record_id: 'wo-1', original_timestamp: '2026-10-03T06:00:00Z', ingestion_timestamp: '2026-10-03T06:00:01Z', canonical_event_type: 'HYDRAULIC_PRESSURE_LOW', canonical_payload: { action: 'Hydraulic return filter replaced' }, raw_source_payload: {}, provenance: {}, attachments: [], context_snapshots: [] }] })
      return response({}, 404)
    }))
    renderPage(<HistoryPage />)
    expect(await screen.findByText('Hydraulic return filter replaced')).toBeInTheDocument()
    expect(screen.getByText(/Semantic matches are intentionally excluded/i)).toBeInTheDocument()
  })

  it('search labels ranking output as Semantic and never as confidence', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/overview') return response(overview)
      if (url === '/api/v1/semantic-search') return response({ available: true, classification: 'Semantic', failure: null, reason: null, results: [{ evidence_id: 'e-history', machine_id: machine.id, component_id: 'pump', session_id: null, incident_id: null, source_type: 'HUMAN_OBSERVATION', canonical_event_type: 'HYDRAULIC_PRESSURE_LOW', original_timestamp: '2026-09-20T08:00:00Z', canonical_payload: { observation: 'slow boom response' }, provenance: {}, similarity_score: 0.82, classification: 'Semantic' }] })
      return response({}, 404)
    }))
    renderPage(<SearchPage />)
    const button = await screen.findByRole('button', { name: /Search/i })
    fireEvent.click(button)
    expect(await screen.findByText('Semantic')).toBeInTheDocument()
    expect(screen.getByText(/similarity ranking score 0.8200/i)).toBeInTheDocument()
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument()
  })

  it('session shows active state and immutable report counts from the latest sync package', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/overview') return response(overview)
      if (url === '/api/v1/sync/status') return response({ machine_id: machine.id, pending_item_count: 0, failed_item_count: 0, conflict_count: 1, latest_package: { package_id: 'pkg-1', session_id: 'session-closed', state: 'CONFLICT', attempt_count: 1, local_revision: 2, report_revision: 1 }, last_transmission_attempt: null, last_acknowledgement: null, last_error: null, transport_configured: true, transport_available: true, transport_checked_at: null, conflicts: [] })
      if (url === '/api/v1/sessions/session-closed/report') return response({ report_id: 'report-1', machine_id: machine.id, session_id: 'session-closed', schema_version: '1.0', generated_at: '2026-10-03T07:00:00Z', operating_summary: { start: '2026-10-03T02:00:00Z', end: '2026-10-03T07:00:00Z', operating_hours: 5, session_state: 'CLOSED' }, incident_summaries: [{}], maintenance_actions: [{}], verification_results: [{}], unresolved_work: [], evidence_manifest: { entries: [{ evidence_id: 'e-1' }] }, sync_metadata: { local_revision: 2, report_revision: 1, acknowledgement_state: 'PENDING' }, checksum: 'abc' })
      return response({}, 404)
    }))
    renderPage(<SessionPage />)
    expect(await screen.findByText('OPEN')).toBeInTheDocument()
    expect(await screen.findByText('Most recent closed-session report')).toBeInTheDocument()
    expect(screen.getByText('1', { selector: 'strong' })).toBeInTheDocument()
  })

  it('return-to-service renders backend-owned blockers', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ state: 'DO_NOT_RETURN', blocking_reasons: [{ code: 'INCIDENT_STATUS_BLOCK', message: 'Open cooling issue blocks return', incident_id: 'incident-2', verification_id: null, evidence_ids: ['e-2'] }], incident_ids: ['incident-2'], verification_ids: [], evidence_ids: ['e-2'], policy_identifier: 'demo.policy', policy_revision: 1 })))
    renderPage(<ReturnToServicePage />)
    expect(await screen.findByText('DO_NOT_RETURN')).toBeInTheDocument()
    expect(screen.getByText('Open cooling issue blocks return')).toBeInTheDocument()
  })

  it('sync renders persisted conflict facts without inventing success', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ machine_id: machine.id, pending_item_count: 0, failed_item_count: 0, conflict_count: 1, latest_package: { package_id: 'pkg-1', session_id: 'session-closed', state: 'CONFLICT', attempt_count: 1, local_revision: 2, report_revision: 1 }, last_transmission_attempt: '2026-10-03T07:05:00Z', last_acknowledgement: '2026-10-03T07:05:00Z', last_error: null, transport_configured: true, transport_available: true, transport_checked_at: '2026-10-03T07:05:00Z', conflicts: [{ conflict_id: 'conflict-1', package_id: 'pkg-1', object_id: 'report-1', local_revision: 2, central_revision: 3, detected_at: '2026-10-03T07:05:00Z', state: 'OPEN', resolution_metadata: {} }] })))
    renderPage(<SyncPage />)
    expect(await screen.findByText('Revision conflict')).toBeInTheDocument()
    expect(screen.getByText('CONFLICT')).toBeInTheDocument()
    expect(screen.queryByText(/^Synchronized$/i)).not.toBeInTheDocument()
  })
})
