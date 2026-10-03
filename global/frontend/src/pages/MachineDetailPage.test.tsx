// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MachineDetailPage } from './MachineDetailPage'

function response(body: unknown) { return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })) }

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/machines/machine-01']}><Routes><Route path="/machines/:machineId" element={<MachineDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('MachineDetailPage', () => {
  it('renders synchronized machine, components, sessions and incidents without a local timeline mutation workflow', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/machines/machine-01') return response({ id: 'machine-01', display_name: 'Loader One', asset_code: 'LD-01', machine_type: 'WHEEL_LOADER', manufacturer: 'Maker', model: 'Model X', site_name: 'North Pit', site_area: 'Bench 4', latest_sync_received_at: '2026-10-03T08:00:00Z', latest_acknowledged_at: '2026-10-03T08:01:00Z', latest_acknowledgement_status: 'ACCEPTED', latest_report_revision: 3 })
      if (url === '/api/v1/machines/machine-01/components') return response({ machine_id: 'machine-01', components: [{ id: 'component-01', machine_id: 'machine-01', display_name: 'Hydraulic Pump', component_type: 'PUMP', manufacturer: null, model: null }] })
      if (url === '/api/v1/machines/machine-01/sessions?limit=25') return response({ machine_id: 'machine-01', items: [{ session_id: 'session-01', machine_id: 'machine-01', started_at: '2026-10-03T06:00:00Z', ended_at: '2026-10-03T08:00:00Z', state: 'CLOSED', operating_hours: 2, latest_report_revision: 3, ingested_at: '2026-10-03T08:00:00Z', updated_at: '2026-10-03T08:00:00Z' }], total: 1, offset: 0, limit: 25 })
      if (url === '/api/v1/machines/machine-01/incidents?limit=25') return response({ items: [{ incident_id: 'incident-01', machine_id: 'machine-01', component_id: 'component-01', status: 'OPEN', created_at: '2026-10-03T07:00:00Z', updated_at: '2026-10-03T08:00:00Z', last_seen_at: '2026-10-03T07:30:00Z' }], total: 1, offset: 0, limit: 25 })
      return response({})
    })
    vi.stubGlobal('fetch', fetchMock)

    renderDetail()

    expect(await screen.findByText('Loader One')).toBeInTheDocument()
    expect(screen.getByText('Hydraulic Pump')).toBeInTheDocument()
    expect(screen.getByText('CLOSED')).toBeInTheDocument()
    expect(screen.getByText('OPEN')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/timeline'))).toBe(false)
  })
})
