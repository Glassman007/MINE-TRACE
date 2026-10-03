// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SyncConflictsPage } from './SyncConflictsPage'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('SyncConflictsPage', () => {
  it('shows both revision metadata without merge actions', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ items: [{ conflict_id: 'c-1', source_machine_id: 'm-1', session_id: 's-1', incoming_package_id: 'p-2', existing_receipt_id: 'r-1', conflict_type: 'SAME_REVISION_CONTENT_MISMATCH', incoming_report_revision: 2, existing_report_revision: 2, incoming_checksum: 'sha256:new', existing_checksum: 'sha256:old', incoming_metadata: { source: 'incoming' }, existing_metadata: { source: 'existing' }, detected_at: '2026-10-03T08:00:00Z', resolution_status: 'UNRESOLVED', resolved_at: null, resolution_notes: null }], total: 1, offset: 0, limit: 20 }), { status: 200, headers: { 'Content-Type': 'application/json' } }))))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter><SyncConflictsPage /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('Existing revision metadata')).toBeInTheDocument(); expect(screen.getByText('Incoming revision metadata')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: /merge/i })).not.toBeInTheDocument()
  })
})
