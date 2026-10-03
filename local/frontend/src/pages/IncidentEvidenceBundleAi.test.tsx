// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentDetailPage } from './IncidentDetailPage'
import type { AIAnalysisResponse } from '../api/ai'
import type { EvidenceBundleResponse } from '../api/evidenceBundle'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

const incident = {
  incident_id: 'incident-01',
  machine_id: 'machine-01',
  status: 'OPEN',
  severity: 'MEDIUM',
  owner_ref: null,
  due_state: 'NOT_SET',
  due_time: null,
  created_at: '2026-10-02T20:00:00Z',
  updated_at: '2026-10-03T01:00:00Z',
  audit_events: [],
}

function bundleEvidence(
  evidenceId: string,
  sourceClassification: 'PRIMARY_INCIDENT_EVIDENCE' | 'EXACT_HISTORY' | 'SEMANTIC_HISTORY',
  sourceType: string,
  eventType: string,
  timestamp: string,
  payload: Record<string, unknown>,
  similarityScore: number | null = null,
) {
  return {
    evidence_id: evidenceId,
    machine_id: 'machine-01',
    component_id: null,
    source_type: sourceType,
    original_source_record_id: `source-${evidenceId}`,
    original_timestamp: timestamp,
    ingestion_timestamp: timestamp,
    canonical_event_type: eventType,
    canonical_payload: payload,
    raw_source_payload: payload,
    provenance: { source: 'test' },
    source_classification: sourceClassification,
    inclusion_reason: sourceClassification,
    relationship_type: sourceClassification === 'PRIMARY_INCIDENT_EVIDENCE' ? 'RELATED' : null,
    deterministic_rule_identifier: null,
    anchor_evidence_id: sourceClassification === 'SEMANTIC_HISTORY' ? 'e-primary' : null,
    similarity_score: similarityScore,
  } as const
}

const primaryEvidence = bundleEvidence('e-primary', 'PRIMARY_INCIDENT_EVIDENCE', 'MACHINE_EVENT', 'PRESSURE_WARNING', '2026-10-03T00:00:00Z', { pressure: 10 })
const exactEvidence = bundleEvidence('e-exact', 'EXACT_HISTORY', 'MAINTENANCE_RECORD', 'INSPECTION', '2026-09-20T00:00:00Z', { note: 'checked' })
const semanticEvidence = bundleEvidence('e-semantic', 'SEMANTIC_HISTORY', 'HUMAN_OBSERVATION', 'OPERATOR_NOTE', '2026-09-18T00:00:00Z', { text: 'pressure felt unstable' }, 0.82)

function completeness(
  statusReason = 'Canonical incident evidence is available.',
  semantic: Partial<EvidenceBundleResponse['completeness']['semantic_retrieval']> = {},
): EvidenceBundleResponse['completeness'] {
  return {
    canonical_readiness_policy: 'evidence-bundle.v1',
    status_reason: statusReason,
    incomplete_sections: [],
    truncated_sections: [],
    semantic_retrieval: {
      configured: true,
      attempted: true,
      failed: false,
      failures: [],
      queried_primary_evidence_ids: ['e-primary'],
      ...semantic,
    },
  }
}

function makeBundle(overrides: Partial<EvidenceBundleResponse> = {}): EvidenceBundleResponse {
  return {
    incident_id: 'incident-01',
    status: 'READY',
    primary_incident_evidence: [primaryEvidence],
    selected_exact_history: [exactEvidence],
    selected_semantic_history: [semanticEvidence],
    verification_context: [],
    evidence_time_context_snapshots: [],
    provenance_index: [{ evidence_id: 'e-primary', original_source_record_id: 'source-e-primary', source_classification: 'PRIMARY_INCIDENT_EVIDENCE', source_type: 'MACHINE_EVENT', provenance: { source: 'ecu' } }],
    completeness: completeness(),
    ...overrides,
  }
}

function installApi(bundle: EvidenceBundleResponse, aiResponse?: AIAnalysisResponse) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (method === 'POST' && url === '/api/v1/incidents/incident-01/ai-analysis') {
      if (!aiResponse) return jsonResponse({ error: { code: 'UNEXPECTED_AI', message: 'No AI response configured' } }, 500)
      return jsonResponse(aiResponse)
    }
    if (method !== 'GET') return jsonResponse({ error: { code: 'UNEXPECTED_MUTATION', message: `${method} ${url}` } }, 500)
    if (url === '/api/v1/incidents/incident-01') return jsonResponse(incident)
    if (url === '/api/v1/incidents/incident-01/evidence') return jsonResponse({ incident_id: 'incident-01', evidence: [] })
    if (url === '/api/v1/incidents/incident-01/audit') return jsonResponse({ incident_id: 'incident-01', audit_events: [] })
    if (url === '/api/v1/incidents/incident-01/verifications') return jsonResponse({ incident_id: 'incident-01', runs: [] })
    if (url === '/api/v1/incidents/incident-01/evidence-bundle') return jsonResponse(bundle)
    if (url === '/api/v1/machines/current') return jsonResponse({ id: 'machine-01', display_name: 'Haul Truck 01', asset_code: null, machine_type: null, manufacturer: null, model: null, site_name: null, site_area: null })
    return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${url}` } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/incidents/incident-01']}>
        <Routes><Route path="/incidents/:incidentId" element={<IncidentDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openBundle() {
  fireEvent.click(await screen.findByRole('button', { name: /Evidence Bundle/i }))
}

async function openAi() {
  fireEvent.click(await screen.findByRole('button', { name: /AI Analysis/i }))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Incident Evidence Bundle', () => {
  it('renders READY with primary, exact and semantic evidence kept distinct', async () => {
    installApi(makeBundle())
    renderDetail()
    await openBundle()

    expect(await screen.findByText('READY')).toBeInTheDocument()
    expect(screen.getByText('PRIMARY INCIDENT EVIDENCE')).toBeInTheDocument()
    expect(screen.getByText('EXACT HISTORY')).toBeInTheDocument()
    expect(screen.getByText('SEMANTIC HISTORY')).toBeInTheDocument()
    expect(screen.getByText('Similarity 0.82')).toBeInTheDocument()
    expect(screen.getByText(/Canonical incident evidence is available/i)).toBeInTheDocument()
  })

  it('renders PARTIAL without treating the bundle as total failure', async () => {
    installApi(makeBundle({ status: 'PARTIAL', completeness: completeness('Semantic enrichment was incomplete.') }))
    renderDetail()
    await openBundle()

    expect(await screen.findByText('PARTIAL')).toBeInTheDocument()
    expect(screen.getByText(/Semantic enrichment was incomplete/i)).toBeInTheDocument()
    expect(screen.getByText('PRIMARY INCIDENT EVIDENCE')).toBeInTheDocument()
  })

  it('renders INSUFFICIENT_EVIDENCE and the backend reason', async () => {
    installApi(makeBundle({
      status: 'INSUFFICIENT_EVIDENCE',
      completeness: completeness('No usable active primary incident evidence.'),
      primary_incident_evidence: [],
      selected_exact_history: [],
      selected_semantic_history: [],
    }))
    renderDetail()
    await openBundle()

    expect(await screen.findByText('INSUFFICIENT_EVIDENCE')).toBeInTheDocument()
    expect(screen.getByText(/No usable active primary incident evidence/i)).toBeInTheDocument()
    expect(screen.getAllByText(/No evidence records returned/i)).toHaveLength(3)
  })

  it('renders semantic retrieval unconfigured as bundle-local degradation', async () => {
    installApi(makeBundle({
      selected_semantic_history: [],
      completeness: completeness('Semantic retrieval is not configured.', { configured: false, attempted: false, failed: false, failures: [], queried_primary_evidence_ids: [] }),
    }))
    renderDetail()
    await openBundle()

    expect(await screen.findByText('Semantic retrieval not configured for this bundle')).toBeInTheDocument()
    expect(screen.queryByText(/Qdrant online/i)).not.toBeInTheDocument()
    expect(screen.getByText('PRIMARY INCIDENT EVIDENCE')).toBeInTheDocument()
  })

  it('renders semantic retrieval failure while deterministic evidence remains available', async () => {
    installApi(makeBundle({
      status: 'PARTIAL',
      selected_semantic_history: [],
      completeness: completeness('Semantic retrieval failed.', { configured: true, attempted: true, failed: true, failures: ['SEMANTIC_INDEX_UNAVAILABLE'], queried_primary_evidence_ids: ['e-primary'] }),
    }))
    renderDetail()
    await openBundle()

    expect(await screen.findByText('Semantic retrieval unavailable; deterministic evidence remains available')).toBeInTheDocument()
    const semanticDetails = screen.getByText('Semantic retrieval details').closest('details')
    expect(semanticDetails).not.toBeNull()
    expect(within(semanticDetails as HTMLElement).getByText('e-primary')).toBeInTheDocument()
    expect(screen.getByText('PRIMARY INCIDENT EVIDENCE')).toBeInTheDocument()
  })
})

describe('Incident AI analysis', () => {
  const validatedResponse: AIAnalysisResponse = {
    result_type: 'VALIDATED_AI',
    fallback: null,
    validated_ai: {
      status: 'VALIDATED',
      summary: 'Pressure warning recurred after a prior inspection.',
      claims: [
        { claim_type: 'EVENT_OCCURRED', text: 'The current pressure warning is recorded in canonical evidence.', evidence_ids: ['e-primary'] },
        { claim_type: 'SIMILAR_HISTORY_FOUND', text: 'A semantically similar historical observation was found.', evidence_ids: ['e-semantic'] },
        { claim_type: 'STATUS_REPORTED', text: 'The inspection record does not establish resolution.', evidence_ids: ['e-exact', 'e-primary'] },
      ],
      limitations: ['Semantic similarity does not prove an identical mechanical cause.'],
    },
  }

  it('runs only after Analyze Evidence and renders backend-validated claims with citations', async () => {
    const fetchMock = installApi(makeBundle(), validatedResponse)
    renderDetail()
    await openAi()

    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/ai-analysis') && init?.method === 'POST')).toBe(false)
    expect(await screen.findByRole('button', { name: 'Analyze Evidence' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze Evidence' }))

    expect(await screen.findByText('VALIDATED')).toBeInTheDocument()
    expect(screen.getByText(/Pressure warning recurred after a prior inspection/i)).toBeInTheDocument()
    expect(screen.getByText('Validated claims')).toBeInTheDocument()
    expect(screen.getByText(/Semantic similarity does not prove an identical mechanical cause/i)).toBeInTheDocument()
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/ai-analysis') && init?.method === 'POST')).toHaveLength(1))
  })

  it('supports an AI claim with multiple clickable citations and highlights bundle evidence', async () => {
    installApi(makeBundle(), validatedResponse)
    renderDetail()
    await openAi()
    fireEvent.click(await screen.findByRole('button', { name: 'Analyze Evidence' }))
    await screen.findByText('VALIDATED')

    const primaryCitations = await screen.findAllByRole('button', { name: /e-primary/i })
    expect(primaryCitations.length).toBeGreaterThan(0)
    fireEvent.click(primaryCitations[0])

    expect(await screen.findByText('PRIMARY INCIDENT EVIDENCE')).toBeInTheDocument()
    await waitFor(() => {
      const highlighted = document.querySelector('[data-bundle-evidence-id="e-primary"]')
      expect(highlighted).toHaveClass('bundle-evidence-card--highlighted')
    })
  })

  const fallbackReasons = [
    'AI_DISABLED',
    'AI_PROVIDER_NOT_CONFIGURED',
    'AI_PROVIDER_UNAVAILABLE',
    'AI_PROVIDER_ERROR',
    'AI_TIMEOUT',
    'MALFORMED_OUTPUT',
    'UNKNOWN_CITATION',
    'PROHIBITED_CLAIM',
    'INSUFFICIENT_EVIDENCE',
  ] as const

  it.each(fallbackReasons)('renders controlled FALLBACK %s without fabricating analysis', async (reason) => {
    const fallbackResponse: AIAnalysisResponse = {
      result_type: 'FALLBACK',
      validated_ai: null,
      fallback: {
        incident_id: 'incident-01',
        reason,
        reason_detail: reason,
        evidence_bundle_status: 'READY',
        primary_evidence: [],
        exact_history: [],
        semantic_history: { attempted: false, configured: false, selected_match_count: 0, state: 'DISABLED', failure_reasons: [] },
        verification: [],
      },
    }
    installApi(makeBundle(), fallbackResponse)
    renderDetail()
    await openAi()
    fireEvent.click(await screen.findByRole('button', { name: 'Analyze Evidence' }))

    expect(await screen.findByText('AI analysis unavailable. Deterministic evidence remains available.')).toBeInTheDocument()
    expect(screen.getByText(reason)).toBeInTheDocument()
    expect(screen.queryByText('Evidence-grounded AI analysis')).not.toBeInTheDocument()
  })
})
