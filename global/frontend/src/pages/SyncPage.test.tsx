// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SyncPage } from './SyncPage'

function response(body: unknown) { return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })) }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('SyncPage', () => {
  it('separates canonical database health from optional Qdrant, embeddings and Groq state', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => String(input).startsWith('/api/v1/sync/health') ? response({ canonical_database: 'ok', unresolved_conflicts: 1, stale_after_hours: 24, semantic: { status: 'UNAVAILABLE', reason: 'qdrant down' }, embeddings: { status: 'AVAILABLE' }, ai: { status: 'DISABLED', reason: 'missing key' }, machines: [{ machine_id: 'm-1', latest_session_id: 's-1', latest_report_revision: 2, latest_receipt_id: 'r-1', latest_received_at: '2026-10-03T08:00:00Z', latest_acknowledged_at: '2026-10-03T08:01:00Z', acknowledgement_status: 'ACCEPTED', unresolved_conflicts: 1, age_seconds: 100, stale: false }] }) : response({ status: 'ok', database: 'ok', database_role: 'canonical_postgresql' })))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter><SyncPage /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('Canonical PostgreSQL')).toBeInTheDocument(); expect(screen.getByText('Qdrant semantic')).toBeInTheDocument(); expect(screen.getByText('Local embeddings')).toBeInTheDocument(); expect(screen.getByText('Groq AI')).toBeInTheDocument(); expect(screen.getByText('ACCEPTED')).toBeInTheDocument()
  })
})
