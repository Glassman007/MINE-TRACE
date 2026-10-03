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
  id: 'incident-01',
  machine_id: 'machine-01',
  status: 'OPEN',
  severity: 'MEDIUM',
  owner_ref: null,
  due_state: 'NOT_SET',
  due_time: null,
  created_at: '2026-10-02T20:00:00Z',
  updated_at: '2026-10-03T01:00:00Z',
}

const primaryEvidence = {
  evidence_id: 'e-primary',
  source_type: 'MACHINE_EVENT',
  canonical_event_type: 'PRESSURE_WARNING',
  original_timestamp: '2026-10-03T00:00:00Z',
  canonical_payload: { pressure: 10 },
}

const exactEvidence = {
  evidence_id: 'e-exact',
  source_type: 'MAINTENANCE_RECORD',
  canonical_event_type: 'INSPECTION',
  original_timestamp: '2026-09-20T00:00:00Z',
  canonical_payload: { note: 'checked' },
}

const semanticEvidence = {
  evidence_id: 'e-semantic',
  source_type: 'HUMAN_OBSERVATION',
  canonical_event_type: 'OPERATOR_NOTE',
  original_timestamp: '2026-09-18T00:00:00Z',
  canonical_payload: { text: 'pressure felt unstable' },
  similarity_score: 0.82,
}

function makeBundle(overrides: Partial<EvidenceBundleResponse> = {}): EvidenceBundleResponse {
  return {
    status: 'READY',
    reason: 'Canonical incident evidence is available.',
    primary_incident_evidence: [primaryEvidence],
    selected_exact_history: [exactEvidence],
    selected_semantic_history: [semanticEvidence],
    verification_context: { runs: [] },
    evidence_time_context_snapshots: [],
    provenance_index: { 'e-primary': { source: 'ecu' } },
    completeness: {
      semantic_retrieval: {
        configured: true,
        attempted: true,
        failed: false,
        failures: [],
        queried_primary_evidence_ids: ['e-primary'],
      },
    },
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
    if (url === '/api/v1/incidents/incident-01/evidence') return jsonResponse([])
    if (url === '/api/v1/incidents/incident-01/audit') return jsonResponse([])
    if (url === '/api/v1/incidents/incident-01/verifications') return jsonResponse([])
    if (url === '/api/v1/incidents/incident-01/evidence-bundle') return jsonResponse(bundle)
    if (url === '/api/v1/machines/machine-01') return jsonResponse({ id: 'machine-01', display_name: 'Haul Truck 01' })
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
    installApi(makeBundle({ status: 'PARTIAL', reason: 'Semantic enrichment was incomplete.' }))
    renderDetail()
    await openBundle()

    expect(await screen.findByText('PARTIAL')).toBeInTheDocument()
    expect(screen.getByText(/Semantic enrichment was incomplete/i)).toBeInTheDocument()
    expect(screen.getByText('PRIMARY INCIDENT EVIDENCE')).toBeInTheDocument()
  })

  it('renders INSUFFICIENT_EVIDENCE and the backend reason', async () => {
    installApi(makeBundle({
      status: 'INSUFFICIENT_EVIDENCE',
      reason: 'No usable active primary incident evidence.',
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
      completeness: {
        semantic_retrieval: {
          configured: false,
          attempted: false,
          failed: false,
          failures: [],
          queried_primary_evidence_ids: [],
        },
      },
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
      reason: 'Semantic retrieval failed.',
      selected_semantic_history: [],
      completeness: {
        semantic_retrieval: {
          configured: true,
          attempted: true,
          failed: true,
          failures: [{ code: 'SEMANTIC_UNAVAILABLE' }],
          queried_primary_evidence_ids: ['e-primary'],
        },
      },
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
    status: 'VALIDATED',
    fallback_reason: null,
    analysis: {
      summary: { text: 'Pressure warning recurred after a prior inspection.', evidence_ids: ['e-primary', 'e-exact'] },
      relevant_observations: [{ text: 'The current warning is machine-generated.', evidence_ids: ['e-primary'] }],
      possible_historical_similarities: [{ text: 'A prior human observation described unstable pressure.', evidence_ids: ['e-semantic'] }],
      unresolved_contradictions: [{ text: 'The inspection record does not establish resolution.', evidence_ids: ['e-exact', 'e-primary'] }],
      evidence_references: ['e-primary', 'e-exact', 'e-semantic'],
    },
  }

  it('runs only after Analyze Evidence and renders VALIDATED claims with citations', async () => {
    const fetchMock = installApi(makeBundle(), validatedResponse)
    renderDetail()
    await openAi()

    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/ai-analysis') && init?.method === 'POST')).toBe(false)
    expect(await screen.findByRole('button', { name: 'Analyze Evidence' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze Evidence' }))

    expect(await screen.findByText('VALIDATED')).toBeInTheDocument()
    expect(screen.getByText(/Pressure warning recurred after a prior inspection/i)).toBeInTheDocument()
    expect(screen.getByText('Relevant observations')).toBeInTheDocument()
    expect(screen.getByText('Possible historical similarities')).toBeInTheDocument()
    expect(screen.getByText('Unresolved contradictions')).toBeInTheDocument()
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

  it.each([
    'LLM_UNAVAILABLE',
    'LLM_TIMEOUT',
    'LLM_ERROR',
    'INVALID_JSON',
    'SCHEMA_VALIDATION_FAILED',
    'CITATION_VALIDATION_FAILED',
    'CLAIM_POLICY_VALIDATION_FAILED',
  ])('renders controlled FALLBACK %s without fabricating analysis', async (reason) => {
    installApi(makeBundle(), { status: 'FALLBACK', analysis: null, fallback_reason: reason })
    renderDetail()
    await openAi()
    fireEvent.click(await screen.findByRole('button', { name: 'Analyze Evidence' }))

    expect(await screen.findByText('AI analysis unavailable. Deterministic evidence remains available.')).toBeInTheDocument()
    expect(screen.getByText(reason)).toBeInTheDocument()
    expect(screen.queryByText('Evidence-grounded AI analysis')).not.toBeInTheDocument()
  })
})
