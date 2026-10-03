// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SearchPage } from './SearchPage'

function renderPage() { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); return render(<QueryClientProvider client={client}><MemoryRouter><SearchPage /></MemoryRouter></QueryClientProvider>) }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('SearchPage', () => {
  it('labels hydrated Qdrant candidates as similar results rather than confidence', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ state: 'AVAILABLE', results: [{ evidence_id: 'e-1', machine_id: 'm-1', component_id: null, session_id: null, incident_ids: [], source_type: 'HUMAN_OBSERVATION', original_timestamp: '2026-10-03T07:00:00Z', ingestion_timestamp: '2026-10-03T08:00:00Z', canonical_event_type: 'NOTE', canonical_payload: { text: 'pump whine' }, provenance: { source: 'edge' }, machine_type: 'HAUL_TRUCK', model: 'MT-100', site: 'North', similarity_score: 0.87, match_type: 'SEMANTIC_SIMILARITY' }] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))))
    renderPage(); fireEvent.change(screen.getByLabelText('Semantic query'), { target: { value: 'pump noise' } }); fireEvent.click(screen.getByRole('button', { name: /search similar evidence/i }))
    expect(await screen.findByText(/Similar result · 0.870/)).toBeInTheDocument()
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument()
    expect(screen.getByText(/pump whine/)).toBeInTheDocument()
  })

  it('shows degraded semantic state without turning the page into a canonical API failure', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ state: 'DEGRADED', reason: 'embedding_unavailable', results: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))))
    renderPage(); fireEvent.change(screen.getByLabelText('Semantic query'), { target: { value: 'pump noise' } }); fireEvent.click(screen.getByRole('button', { name: /search similar evidence/i }))
    expect(await screen.findByText('Semantic capability degraded')).toBeInTheDocument()
    expect(screen.getByText('embedding_unavailable')).toBeInTheDocument()
  })
})
