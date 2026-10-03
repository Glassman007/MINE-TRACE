// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentsPage } from './IncidentsPage'

function response(body: unknown) { return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })) }
function renderPage(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/incidents" element={<IncidentsPage />} /></Routes></MemoryRouter></QueryClientProvider>)
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('IncidentsPage', () => {
  it('uses the exact global PostgreSQL filter contract', async () => {
    const fetchMock = vi.fn(() => response({ items: [], total: 0, offset: 0, limit: 25 }))
    vi.stubGlobal('fetch', fetchMock)
    renderPage('/incidents?machine=m-1&component=c-1&status=OPEN&model=HX&site=North&start=2026-10-01T00%3A00%3A00Z&end=2026-10-03T00%3A00%3A00Z')

    expect(await screen.findByText('No incidents')).toBeInTheDocument()
    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), 'http://mine-trace.test')
    expect(url.searchParams.get('machine')).toBe('m-1')
    expect(url.searchParams.get('component')).toBe('c-1')
    expect(url.searchParams.get('status')).toBe('OPEN')
    expect(url.searchParams.get('model')).toBe('HX')
    expect(url.searchParams.get('site')).toBe('North')
    expect(url.searchParams.has('severity')).toBe(false)
  })

  it('renders canonical incident IDs and synchronized model/site metadata', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ items: [{ incident_id: 'incident-001', machine_id: 'machine-001', component_id: null, status: 'OPEN', severity: null, owner_ref: null, due_state: null, due_time: null, first_seen_at: null, last_seen_at: '2026-10-03T01:00:00Z', source_report_revision: 1, machine_model: 'HX', site_name: 'North', created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T01:00:00Z' }], total: 1, offset: 0, limit: 25 })))
    renderPage('/incidents')
    expect(await screen.findByText('OPEN')).toBeInTheDocument()
    expect(screen.getByText(/North · HX/)).toBeInTheDocument()
    expect(screen.getByText('incident-001')).toBeInTheDocument()
  })
})
