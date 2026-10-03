// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ComponentDetailPage } from './ComponentDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

const machine = { id: 'machine-01', display_name: 'Haul Truck Alpha', asset_code: 'HT-01', machine_type: 'HAUL_TRUCK', manufacturer: null, model: null, site_name: null, site_area: null }
const component = { id: 'component-01', machine_id: 'machine-01', display_name: 'Brake Assembly', component_type: 'BRAKE', manufacturer: null, model: null }
const timelineEvent = {
  evidence_id: 'evidence-maint-01', machine_id: 'machine-01', component_id: 'component-01', source_type: 'MAINTENANCE_RECORD', original_source_record_id: 'maint-1',
  original_timestamp: '2026-10-03T09:00:00Z', ingestion_timestamp: '2026-10-03T09:01:00Z', canonical_event_type: 'REPAIR', canonical_payload: {}, raw_source_payload: {}, provenance: {}, context_snapshots: [], attachments: [],
}
const incident = { incident_id: 'incident-01', machine_id: 'machine-01', status: 'RECURRED', severity: null, owner_ref: null, due_state: null, due_time: null, created_at: '2026-10-03T08:00:00Z', updated_at: '2026-10-03T10:00:00Z' }

function renderPage(componentId = 'component-01') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/components/${componentId}`]}>
        <Routes><Route path="/components/:componentId" element={<ComponentDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function installDetailedApi(componentBody: Record<string, unknown> = component) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/v1/components/component-01') return jsonResponse(componentBody)
    if (url === '/api/v1/machines/current') return jsonResponse(machine)
    if (url === '/api/v1/machines/machine-01/timeline?component_id=component-01') return jsonResponse({ machine_id: 'machine-01', component_id: 'component-01', evidence: [timelineEvent] })
    if (url.startsWith('/api/v1/incidents?')) {
      const parsed = new URL(url, 'http://mine-trace.test')
      if (parsed.searchParams.get('machine_id') === 'machine-01' && parsed.searchParams.get('offset') === '0' && parsed.searchParams.get('limit') === '200') {
        return jsonResponse({ items: [incident], total: 1, offset: 0, limit: 200 })
      }
    }
    if (url === '/api/v1/incidents/incident-01/evidence') return jsonResponse({ incident_id: 'incident-01', evidence: [{ evidence_id: 'evidence-maint-01', link_id: 'link-1', machine_id: 'machine-01', component_id: 'component-01', source_type: 'MAINTENANCE_RECORD', canonical_event_type: 'REPAIR', canonical_payload: {}, raw_source_payload: {}, provenance: {}, original_source_record_id: 'maint-1', original_timestamp: '2026-10-03T09:00:00Z', relationship_type: 'RECURRENCE', is_active: true, link_reason: 'rule', linked_at: '2026-10-03T09:01:00Z', unlinked_at: null, deterministic_rule_identifier: 'rule-v1' }] })
    if (url === '/api/v1/incidents/incident-01/verifications') return jsonResponse({ incident_id: 'incident-01', runs: [{ id: 'verification-01', incident_id: 'incident-01', verification_rule_id: 'rule-01', rule_identifier: 'verify-v1', rule_name: 'Brake verification', rule_type: 'NO_EVENT', window_minutes: 30, result: 'RECURRENCE_DETECTED', started_at: '2026-10-03T09:30:00Z', window_ends_at: '2026-10-03T10:00:00Z', completed_at: '2026-10-03T10:00:00Z', evidence_event_ids: ['evidence-maint-01'] }] })
    return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${url}` } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('ComponentDetailPage', () => {
  it('renders exact canonical component history, linked incident, recurrence, repair, and verification state', async () => {
    installDetailedApi()
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Brake Assembly' })).toBeInTheDocument()
    expect((await screen.findAllByText('REPAIR')).length).toBeGreaterThan(0)
    expect(screen.getByText('Linked incidents and recurrence')).toBeInTheDocument()
    expect(screen.getByText('RECURRED')).toBeInTheDocument()
    expect(screen.getByText('RECURRENCE_DETECTED')).toBeInTheDocument()
    expect(screen.getByText(/None derivable from maintenance evidence/i)).not.toBeInTheDocument()
    expect(screen.getByText(/This section is not semantic similarity/i)).toBeInTheDocument()
    expect(screen.getByText('Maintenance and repair history')).toBeInTheDocument()
  })



  it('shows explicit empty states instead of inventing component history', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/components/component-01') return jsonResponse(component)
      if (url === '/api/v1/machines/current') return jsonResponse(machine)
      if (url === '/api/v1/machines/machine-01/timeline?component_id=component-01') return jsonResponse({ machine_id: 'machine-01', component_id: 'component-01', evidence: [] })
      if (url.startsWith('/api/v1/incidents?')) return jsonResponse({ items: [], total: 0, offset: 0, limit: 200 })
      return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${url}` } }, 404)
    }))
    renderPage()
    expect(await screen.findByText('No component evidence')).toBeInTheDocument()
    expect(screen.getByText('No maintenance or repair evidence')).toBeInTheDocument()
    expect(screen.getByText('No linked incidents')).toBeInTheDocument()
    expect(screen.getByText('No verification runs')).toBeInTheDocument()
  })

  it('returns a frontend 404 state when the backend says the component does not exist', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/components/missing') return jsonResponse({ error: { code: 'COMPONENT_NOT_FOUND', message: 'missing' } }, 404)
      if (url === '/api/v1/machines/current') return jsonResponse(machine)
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 200 })
    }))
    renderPage('missing')
    expect(await screen.findByText('Component not found')).toBeInTheDocument()
  })

  it('never switches to a component-owned foreign machine and scopes dependent reads to This Machine', async () => {
    const fetchMock = installDetailedApi({ ...component, machine_id: 'machine-foreign' })
    renderPage()
    expect(await screen.findByText('Component is not part of This Machine')).toBeInTheDocument()
    const urls = fetchMock.mock.calls.map(([input]) => String(input))
    expect(urls.some((url) => url.includes('/machines/machine-foreign/'))).toBe(false)
    expect(urls.some((url) => url.includes('/machines/machine-01/timeline'))).toBe(true)
  })

  it('shows loading while canonical component identity is unresolved', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    renderPage()
    expect(screen.getByRole('status', { name: 'Component detail loading' })).toBeInTheDocument()
  })
})
