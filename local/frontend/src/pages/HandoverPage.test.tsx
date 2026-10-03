// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HandoverDetailPage } from './HandoverDetailPage'
import { HandoverPage } from './HandoverPage'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

const item = {
  id: 'handover-item-01',
  incident_id: 'incident-01',
  severity: 'HIGH',
  owner_ref: 'shift-lead',
  status: 'OPEN',
  due_state: 'DUE_SOON',
  due_time: '2026-10-03T04:00:00Z',
}

const packet = {
  id: 'packet-01',
  created_at: '2026-10-03T01:00:00Z',
  acknowledged_at: null,
  items: [item],
}

const incident = {
  incident_id: 'incident-01',
  machine_id: 'machine-01',
  status: 'OPEN',
  severity: 'HIGH',
  owner_ref: 'shift-lead',
  due_state: 'DUE_SOON',
  due_time: '2026-10-03T04:00:00Z',
  created_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:30:00Z',
}

const machine = {
  id: 'machine-01',
  display_name: 'Haul Truck Alpha',
  asset_code: 'HT-A',
  machine_type: 'HAUL_TRUCK',
  manufacturer: null,
  model: null,
  site_name: null,
  site_area: null,
}

function renderRoutes(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/handover" element={<HandoverPage />} />
          <Route path="/handover/:packetId" element={<HandoverDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function installDetailApi(options: { acknowledged?: boolean; duplicateAck?: boolean; notFound?: boolean } = {}) {
  let acknowledgedAt = options.acknowledged ? '2026-10-03T01:10:00Z' : null
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (method === 'GET' && url === '/api/v1/handovers/packet-01') {
      if (options.notFound) return jsonResponse({ error: { code: 'HANDOVER_NOT_FOUND', message: 'Packet not found' } }, 404)
      return jsonResponse({ ...packet, acknowledged_at: acknowledgedAt })
    }
    if (method === 'GET' && url === '/api/v1/incidents/incident-01') return jsonResponse(incident)
    if (method === 'GET' && url === '/api/v1/machines/current') return jsonResponse(machine)
    if (method === 'POST' && url === '/api/v1/handovers/packet-01/acknowledge') {
      if (options.duplicateAck) {
        acknowledgedAt = '2026-10-03T01:11:00Z'
        return jsonResponse({ error: { code: 'HANDOVER_ALREADY_ACKNOWLEDGED', message: 'Packet was already acknowledged' } }, 409)
      }
      acknowledgedAt = '2026-10-03T01:12:00Z'
      return jsonResponse({ ...packet, acknowledged_at: acknowledgedAt })
    }
    return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${method} ${url}` } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Shift handover workflow', () => {
  it('creates a packet from the backend and navigates to the returned packet', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'POST' && url === '/api/v1/handovers') return jsonResponse(packet)
      if (method === 'GET' && url === '/api/v1/handovers/packet-01') return jsonResponse(packet)
      if (method === 'GET' && url === '/api/v1/incidents/incident-01') return jsonResponse(incident)
      if (method === 'GET' && url === '/api/v1/machines/current') return jsonResponse(machine)
      return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${method} ${url}` } }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoutes('/handover')

    fireEvent.click(screen.getByRole('button', { name: 'Create handover' }))

    expect(await screen.findByText('Handover Packet')).toBeInTheDocument()
    expect(await screen.findByText('Haul Truck Alpha')).toBeInTheDocument()
    expect(screen.getByText('shift-lead')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input, init]) => String(input) === '/api/v1/handovers' && init?.method === 'POST')).toBe(true)
    expect(fetchMock.mock.calls.some(([input, init]) => String(input) === '/api/v1/handovers' && (init?.method ?? 'GET') === 'GET')).toBe(false)
  })

  it('retrieves a packet through its reload-safe detail route and resolves machine context', async () => {
    installDetailApi()
    renderRoutes('/handover/packet-01')

    expect(await screen.findByText('Haul Truck Alpha')).toBeInTheDocument()
    expect(screen.getByText('OPEN')).toBeInTheDocument()
    expect(screen.getByText('HIGH')).toBeInTheDocument()
    expect(screen.getByText('DUE_SOON')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open incident' })).toHaveAttribute('href', '/incidents/incident-01')
    expect(screen.getByText(/handover-time snapshot/i)).toBeInTheDocument()
  })

  it('requires confirmation before acknowledgement and refreshes persisted acknowledgement state', async () => {
    const fetchMock = installDetailApi()
    renderRoutes('/handover/packet-01')

    const acknowledgeButton = await screen.findByRole('button', { name: 'Acknowledge handover' })
    fireEvent.click(acknowledgeButton)
    expect(screen.getAllByText(/does not resolve, verify, close/i).length).toBeGreaterThan(0)
    expect(fetchMock.mock.calls.filter(([input, init]) => String(input).endsWith('/acknowledge') && init?.method === 'POST')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge receipt' }))

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input, init]) => String(input).endsWith('/acknowledge') && init?.method === 'POST')).toHaveLength(1)
    })
    expect(await screen.findByText(/Acknowledged at/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Acknowledge handover' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /close all incidents/i })).not.toBeInTheDocument()
  })

  it('renders duplicate acknowledgement as an existing-state conflict', async () => {
    installDetailApi({ duplicateAck: true })
    renderRoutes('/handover/packet-01')

    fireEvent.click(await screen.findByRole('button', { name: 'Acknowledge handover' }))
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge receipt' }))

    expect(await screen.findByText('Already acknowledged')).toBeInTheDocument()
    expect(screen.getByText(/HANDOVER_ALREADY_ACKNOWLEDGED|acknowledged previously/i)).toBeInTheDocument()
  })

  it('renders already acknowledged packets without exposing a second acknowledgement action', async () => {
    installDetailApi({ acknowledged: true })
    renderRoutes('/handover/packet-01')

    expect(await screen.findByText(/Acknowledged at/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Acknowledge handover' })).not.toBeInTheDocument()
  })

  it('renders a dedicated 404 state for an unknown packet', async () => {
    installDetailApi({ notFound: true })
    renderRoutes('/handover/packet-01')

    expect(await screen.findByText('Handover packet not found')).toBeInTheDocument()
  })
})
