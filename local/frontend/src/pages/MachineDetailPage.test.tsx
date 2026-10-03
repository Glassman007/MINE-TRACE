// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MachineDetailPage } from './MachineDetailPage'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function installMachineApi() {
  const machine = {
    id: 'machine-01',
    display_name: 'Loader One',
    asset_code: 'LD-01',
    machine_type: 'WHEEL_LOADER',
    manufacturer: 'Maker',
    model: 'Model X',
    site_name: 'North Pit',
    site_area: 'Bench 4',
  }
  const components = [{
    id: 'component-01',
    machine_id: 'machine-01',
    display_name: 'Hydraulic Pump',
    component_type: 'PUMP',
    manufacturer: null,
    model: null,
  }]
  const timeline = [{
    id: 'evidence-01',
    machine_id: 'machine-01',
    component_id: 'component-01',
    source_type: 'MACHINE_EVENT',
    original_source_record_id: 'source-01',
    original_timestamp: '2026-10-03T08:00:00+05:30',
    ingestion_timestamp: '2026-10-03T10:00:00+05:30',
    canonical_event_type: 'PRESSURE_WARNING',
    canonical_payload: { pressure: 12 },
    raw_source_payload: { raw_pressure: 12 },
    provenance: { source: 'ecu' },
    context_snapshots: [],
    attachments: [],
  }]

  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/v1/machines/current') return jsonResponse(machine)
    if (url === '/api/v1/machines/current/components') return jsonResponse({ machine_id: 'machine-01', components })
    if (url.startsWith('/api/v1/machines/machine-01/timeline')) return jsonResponse({ machine_id: 'machine-01', component_id: url.includes('component_id=component-01') ? 'component-01' : null, evidence: timeline.map(({ id, ...event }) => ({ ...event, evidence_id: id })) })
    if (url.startsWith('/api/v1/incidents?')) return jsonResponse({ items: [], total: 0, offset: 0, limit: 50 })
    return jsonResponse({ error: { code: 'NOT_FOUND', message: 'Unexpected URL' } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderDetail() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/machines/machine-01']}>
        <Routes>
          <Route path="/machines/:machineId" element={<MachineDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('MachineDetailPage', () => {
  it('clicking a component refetches the backend timeline with component_id', async () => {
    const fetchMock = installMachineApi()
    renderDetail()

    const component = await screen.findByRole('button', { name: /Hydraulic Pump/i })
    fireEvent.click(component)

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/timeline?component_id=component-01'))).toBe(true)
    })
  })

  it('shows original occurrence time separately from ingestion time', async () => {
    installMachineApi()
    renderDetail()

    await screen.findByText('PRESSURE_WARNING')
    expect(screen.getByText('Occurred')).toBeInTheDocument()
    expect(screen.getByText('Ingested')).toBeInTheDocument()
  })

  it('refuses a route for another machine instead of fetching or switching to it', async () => {
    const fetchMock = installMachineApi()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/machines/machine-foreign']}>
          <Routes><Route path="/machines/:machineId" element={<MachineDetailPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Machine is not This Machine')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('machine-foreign'))).toBe(false)
  })
})
