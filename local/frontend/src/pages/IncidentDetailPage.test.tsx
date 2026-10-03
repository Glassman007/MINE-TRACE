// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentDetailPage } from './IncidentDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

const detail = {
  incident_id: 'incident-01',
  machine_id: 'machine-01',
  status: 'OPEN',
  severity: null,
  owner_ref: null,
  due_state: null,
  due_time: null,
  created_at: null,
  updated_at: '2026-10-03T01:00:00Z',
  audit_events: [],
}

function installApi(options: { notFound?: boolean; evidenceError?: boolean } = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method && init.method !== 'GET') return jsonResponse({ error: { code: 'UNEXPECTED_MUTATION', message: 'No mutation expected' } }, 500)
    if (url === '/api/v1/incidents/incident-01') {
      if (options.notFound) return jsonResponse({ error: { code: 'INCIDENT_NOT_FOUND', message: 'Not found' } }, 404)
      return jsonResponse(detail)
    }
    if (url === '/api/v1/incidents/incident-01/evidence') {
      if (options.evidenceError) return jsonResponse({ error: { code: 'SERVER_ERROR', message: 'Evidence failed' } }, 500)
      return jsonResponse({ incident_id: 'incident-01', evidence: [{
        link_id: 'link-01',
        evidence_id: 'evidence-01',
        machine_id: 'machine-01',
        component_id: null,
        relationship_type: 'RELATED',
        link_reason: 'deterministic match',
        deterministic_rule_identifier: 'RULE-1',
        is_active: false,
        linked_at: '2026-10-02T22:00:00Z',
        unlinked_at: '2026-10-03T00:00:00Z',
        source_type: 'MACHINE_EVENT',
        original_source_record_id: 'ecu-55',
        original_timestamp: '2026-10-02T21:59:00Z',
        canonical_event_type: 'PRESSURE_WARNING',
        canonical_payload: { pressure: 10 },
        raw_source_payload: { p: 10 },
        provenance: { source: 'ecu' },
      }] })
    }
    if (url === '/api/v1/incidents/incident-01/audit') return jsonResponse({ incident_id: 'incident-01', audit_events: [{
      id: 'audit-01',
      action: 'STATUS_CHANGED',
      occurred_at: '2026-10-03T00:10:00Z',
      payload: { evidence_id: 'evidence-01', detail: { raw: true } },
    }] })
    if (url === '/api/v1/incidents/incident-01/verifications') return jsonResponse({ incident_id: 'incident-01', runs: [] })
    if (url === '/api/v1/incidents/incident-01/evidence-bundle') return jsonResponse({ incident_id: 'incident-01', status: 'PARTIAL', primary_incident_evidence: [], selected_exact_history: [], selected_semantic_history: [], verification_context: [], evidence_time_context_snapshots: [], provenance_index: [], completeness: { canonical_readiness_policy: 'evidence-bundle.v1', status_reason: 'partial', incomplete_sections: [], truncated_sections: [], semantic_retrieval: { configured: false, attempted: false, failed: false, failures: [], queried_primary_evidence_ids: [] } } })
    if (url === '/api/v1/machines/current') return jsonResponse({ id: 'machine-01', display_name: 'Haul Truck 01', asset_code: 'HT-01', machine_type: 'HAUL_TRUCK', manufacturer: null, model: null, site_name: null, site_area: null })
    return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${url}` } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/incidents/incident-01']}>
        <Routes><Route path="/incidents/:incidentId" element={<IncidentDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('IncidentDetailPage', () => {
  it('renders null authoritative fields without invented incident metrics', async () => {
    installApi()
    renderDetail()
    expect((await screen.findAllByText('Haul Truck 01')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Not set').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText(/risk score/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/root cause/i)).not.toBeInTheDocument()
  })

  it('keeps inactive evidence associations visible and exposes evidence structure', async () => {
    installApi()
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /Evidence$/i }))
    expect(await screen.findByText('INACTIVE')).toBeInTheDocument()
    expect(screen.getByText('PRESSURE_WARNING')).toBeInTheDocument()
    expect(screen.getByText('RULE-1')).toBeInTheDocument()
    expect(screen.getByText('Canonical payload')).toBeInTheDocument()
    expect(screen.getByText('Provenance')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Move evidence/i })).not.toBeInTheDocument()
  })

  it('renders backend audit actions with the generic audit component', async () => {
    installApi()
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /Audit/i }))
    expect(await screen.findByText('STATUS_CHANGED')).toBeInTheDocument()
    expect(screen.getByText('Structured audit payload')).toBeInTheDocument()
  })

  it('renders a section-level API error without hiding the incident workspace', async () => {
    installApi({ evidenceError: true })
    renderDetail()
    expect((await screen.findAllByText('Haul Truck 01')).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: /Evidence$/i }))
    expect(await screen.findByText('Evidence unavailable')).toBeInTheDocument()
  })

  it('renders a dedicated 404 state when the incident does not exist', async () => {
    installApi({ notFound: true })
    renderDetail()
    expect(await screen.findByText('Incident not found')).toBeInTheDocument()
  })

  it('shows a loading state while the incident request is unresolved', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    renderDetail()
    expect(screen.getByRole('status', { name: 'Incident detail loading' })).toBeInTheDocument()
  })

  it('does not call AI analysis merely by opening the AI tab', async () => {
    const fetchMock = installApi()
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /AI Analysis/i }))
    expect(await screen.findByRole('button', { name: 'Analyze Evidence' })).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
    })
  })
})

function installAuthoritativeActionApi(options: { moveConflict?: boolean; initialStatus?: string } = {}) {
  let incidentStatus = options.initialStatus ?? 'OPEN'
  let evidenceActive = true
  let verificationRuns: Array<Record<string, unknown>> = []

  const actionFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (method === 'POST' && url === '/api/v1/incidents/incident-01/evidence/evidence-01/move') {
      if (options.moveConflict) return jsonResponse({ error: { code: 'INCIDENT_CORRECTION_CONFLICT', message: 'Association changed' } }, 409)
      const body = JSON.parse(String(init?.body)) as { target_incident_id: string; reason: string }
      expect(body).toEqual({ target_incident_id: 'incident-02', reason: 'belongs with the second incident' })
      evidenceActive = false
      return jsonResponse({ status: 'MOVED' })
    }

    if (method === 'POST' && url === '/api/v1/incidents/incident-01/split') {
      const body = JSON.parse(String(init?.body)) as { evidence_ids: string[]; reason: string }
      expect(body).toEqual({ evidence_ids: ['evidence-01'], reason: 'separate mechanical issue' })
      evidenceActive = false
      return jsonResponse({ new_incident_id: 'incident-new' })
    }

    if (method === 'POST' && url === '/api/v1/incidents/incident-01/verification') {
      incidentStatus = 'VERIFYING'
      verificationRuns = [{
        id: 'run-01',
        incident_id: 'incident-01',
        verification_rule_id: 'rule-01',
        rule_name: 'No recurrence',
        rule_identifier: 'NO_EVENT-1',
        rule_type: 'NO_EVENT',
        window_minutes: 30,
        started_at: '2026-10-03T01:00:00Z',
        window_ends_at: '2026-10-03T01:30:00Z',
        completed_at: null,
        result: null,
        evidence_event_ids: [],
      }]
      return jsonResponse(verificationRuns[0])
    }

    if (method === 'POST' && url === '/api/v1/verifications/evaluate-due') {
      incidentStatus = 'VERIFIED'
      verificationRuns = verificationRuns.map((run) => ({ ...run, result: 'SUCCEEDED', completed_at: '2026-10-03T01:31:00Z' }))
      return jsonResponse({ evaluated: verificationRuns })
    }

    if (method !== 'GET') return jsonResponse({ error: { code: 'UNEXPECTED_MUTATION', message: `${method} ${url}` } }, 500)

    if (url === '/api/v1/incidents/incident-01') return jsonResponse({ ...detail, status: incidentStatus })
    if (url === '/api/v1/incidents/incident-01/evidence') return jsonResponse({ incident_id: 'incident-01', evidence: [{
      link_id: 'link-01',
      evidence_id: 'evidence-01',
      machine_id: 'machine-01',
      component_id: null,
      relationship_type: 'RELATED',
      link_reason: 'deterministic match',
      deterministic_rule_identifier: 'RULE-1',
      is_active: evidenceActive,
      linked_at: '2026-10-02T22:00:00Z',
      unlinked_at: evidenceActive ? null : '2026-10-03T01:05:00Z',
      source_type: 'MACHINE_EVENT',
      original_source_record_id: 'ecu-55',
      original_timestamp: '2026-10-02T21:59:00Z',
      canonical_event_type: 'PRESSURE_WARNING',
      canonical_payload: { pressure: 10 },
      raw_source_payload: { p: 10 },
      provenance: { source: 'ecu' },
    }] })
    if (url === '/api/v1/incidents/incident-01/audit') return jsonResponse({ incident_id: 'incident-01', audit_events: [] })
    if (url === '/api/v1/incidents/incident-01/verifications') return jsonResponse({ incident_id: 'incident-01', runs: verificationRuns })
    if (url === '/api/v1/verifications/run-01') return jsonResponse(verificationRuns[0] ?? {})
    if (url === '/api/v1/incidents/incident-01/evidence-bundle') return jsonResponse({ incident_id: 'incident-01', status: 'READY', primary_incident_evidence: [], selected_exact_history: [], selected_semantic_history: [], verification_context: [], evidence_time_context_snapshots: [], provenance_index: [], completeness: { canonical_readiness_policy: 'evidence-bundle.v1', status_reason: 'ready', incomplete_sections: [], truncated_sections: [], semantic_retrieval: { configured: false, attempted: false, failed: false, failures: [], queried_primary_evidence_ids: [] } } })
    if (url === '/api/v1/machines/current') return jsonResponse({ id: 'machine-01', display_name: 'Haul Truck 01', asset_code: 'HT-01', machine_type: 'HAUL_TRUCK', manufacturer: null, model: null, site_name: null, site_area: null })
    if (url.startsWith('/api/v1/incidents?') && url.includes('machine_id=machine-01')) return jsonResponse({ items: [
      { ...detail, status: incidentStatus },
      { incident_id: 'incident-02', machine_id: 'machine-01', status: 'OPEN', severity: null, owner_ref: null, due_state: null, due_time: null, created_at: '2026-10-02T20:00:00Z', updated_at: '2026-10-03T00:30:00Z' },
    ], total: 2, offset: 0, limit: 100 })
    if (url === '/api/v1/overview') return jsonResponse({ machine: { id: 'machine-01', display_name: 'Haul Truck 01', asset_code: 'HT-01', machine_type: 'HAUL_TRUCK', manufacturer: null, model: null, site_name: null, site_area: null }, active_session: null, operating_state: null, unresolved_incident_count: 2, counts: { components: 0, evidence: 1, incidents: 2, incidents_by_status: { OPEN: incidentStatus === 'OPEN' ? 2 : 1, VERIFYING: incidentStatus === 'VERIFYING' ? 1 : 0, VERIFIED: incidentStatus === 'VERIFIED' ? 1 : 0, RECURRED: 0 } }, return_to_service: { state: 'VERIFICATION_REQUIRED', blocking_reasons: [], policy_identifier: 'test', policy_revision: 1 }, sync: { transport_configured: false } })
    return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${url}` } }, 404)
  })

  vi.stubGlobal('fetch', actionFetch)
  return actionFetch
}

describe('IncidentDetailPage authoritative actions', () => {
  it('moves only an active association and refetches authoritative evidence instead of deleting it locally', async () => {
    const fetchMock = installAuthoritativeActionApi()
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /Evidence$/i }))
    expect(await screen.findByText('ACTIVE')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Move evidence/i }))

    const target = await screen.findByRole('combobox', { name: /Target incident/i })
    fireEvent.change(target, { target: { value: 'incident-02' } })
    fireEvent.change(screen.getByPlaceholderText(/Why is this association incorrect/i), { target: { value: 'belongs with the second incident' } })
    fireEvent.click(screen.getByRole('button', { name: /Review move/i }))
    fireEvent.click(await screen.findByRole('button', { name: /Move association/i }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/evidence/evidence-01/move') && init?.method === 'POST')).toBe(true))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/v1/incidents/incident-01/evidence' && (!init?.method || init.method === 'GET')).length).toBeGreaterThan(1))
    expect(await screen.findByText('INACTIVE')).toBeInTheDocument()
    expect(screen.getByText('PRESSURE_WARNING')).toBeInTheDocument()
  })

  it('splits selected active evidence, refreshes server state, and offers the returned incident link', async () => {
    const fetchMock = installAuthoritativeActionApi()
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /Evidence$/i }))
    fireEvent.click(await screen.findByRole('button', { name: /Split evidence/i }))
    fireEvent.click(screen.getByRole('checkbox', { name: /Select evidence evidence-01 for split/i }))
    fireEvent.change(screen.getByPlaceholderText(/Why should these evidence associations become a separate incident/i), { target: { value: 'separate mechanical issue' } })
    fireEvent.click(screen.getByRole('button', { name: /Review split/i }))
    fireEvent.click(await screen.findByRole('button', { name: /^Split incident$/i }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/v1/incidents/incident-01/split' && init?.method === 'POST')).toBe(true))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/v1/incidents/incident-01/evidence').length).toBeGreaterThan(1))
    expect(await screen.findByText('Created incident')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open new incident/i })).toHaveAttribute('href', '/incidents/incident-new')
    expect(await screen.findByText('INACTIVE')).toBeInTheDocument()
  })

  it('starts verification only by explicit action and then refetches incident and verification history', async () => {
    const fetchMock = installAuthoritativeActionApi()
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /Verification$/i }))
    expect(await screen.findByRole('button', { name: /Start Verification/i })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/verification') && init?.method === 'POST')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: /Start Verification/i }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/v1/incidents/incident-01/verification' && init?.method === 'POST')).toBe(true))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/v1/incidents/incident-01').length).toBeGreaterThan(1))
    expect(await screen.findByText('No recurrence')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Start Verification/i })).not.toBeInTheDocument()
  })

  it('never posts evaluate-due automatically and refreshes authoritative state after deliberate evaluation', async () => {
    const fetchMock = installAuthoritativeActionApi({ initialStatus: 'VERIFYING' })
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /Verification$/i }))
    const evaluateButton = await screen.findByRole('button', { name: /Evaluate due verifications/i })
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/v1/verifications/evaluate-due' && init?.method === 'POST')).toBe(false)

    fireEvent.click(evaluateButton)
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/v1/verifications/evaluate-due' && init?.method === 'POST')).toBe(true))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/v1/incidents/incident-01').length).toBeGreaterThan(1))
    expect(await screen.findByText(/Due verification evaluation completed/i)).toBeInTheDocument()
  })

  it('renders 409 correction conflicts as meaningful state conflicts without hiding evidence', async () => {
    installAuthoritativeActionApi({ moveConflict: true })
    renderDetail()
    fireEvent.click(await screen.findByRole('button', { name: /Evidence$/i }))
    fireEvent.click(await screen.findByRole('button', { name: /Move evidence/i }))
    fireEvent.change(await screen.findByRole('combobox', { name: /Target incident/i }), { target: { value: 'incident-02' } })
    fireEvent.change(screen.getByPlaceholderText(/Why is this association incorrect/i), { target: { value: 'belongs with the second incident' } })
    fireEvent.click(screen.getByRole('button', { name: /Review move/i }))
    fireEvent.click(await screen.findByRole('button', { name: /Move association/i }))

    expect(await screen.findByText(/State conflict/i)).toBeInTheDocument()
    expect(screen.getByText(/INCIDENT_CORRECTION_CONFLICT/i)).toBeInTheDocument()
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
    expect(screen.getByText('PRESSURE_WARNING')).toBeInTheDocument()
  })
})
