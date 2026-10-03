// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OverviewPage } from './OverviewPage'

const localOverview = {
  machine: {
    id: 'machine-01',
    display_name: 'Haul Truck Alpha',
    asset_code: 'HT-01',
    machine_type: 'HAUL_TRUCK',
    manufacturer: 'MineCo',
    model: 'HX',
    site_name: 'North Pit',
    site_area: 'Bench 2',
  },
  active_session: null,
  operating_state: null,
  unresolved_incident_count: 2,
  counts: {
    components: 4,
    evidence: 12,
    incidents: 3,
    incidents_by_status: { OPEN: 1, VERIFYING: 1, VERIFIED: 1, RECURRED: 0 },
  },
  return_to_service: {
    state: 'VERIFICATION_REQUIRED',
    blocking_reasons: [{ code: 'VERIFICATION_RUN_PENDING', message: 'Persisted verification run is incomplete', incident_id: 'incident-01', verification_id: null, evidence_ids: [] }],
    policy_identifier: 'local.return-to-service.v1',
    policy_revision: 1,
  },
  sync: {
    transport_configured: true,
    transport_available: null,
    transport_checked_at: null,
    latest_package_state: 'PENDING',
    last_acknowledgement: null,
    last_error: null,
  },
}

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><OverviewPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('This Machine overview', () => {
  it('uses only the local overview endpoint and renders backend-owned machine/count/clearance facts', async () => {
    const fetchMock = vi.fn(() => response(localOverview))
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByRole('heading', { name: 'This Machine' })).toBeInTheDocument()
    expect(screen.getByText('Haul Truck Alpha')).toBeInTheDocument()
    expect(screen.getByText('VERIFICATION_REQUIRED')).toBeInTheDocument()
    expect(screen.getAllByText('Not yet measured').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('2', { selector: '.metric-card__value' })).toBeInTheDocument()

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/overview', expect.objectContaining({ method: 'GET' }))
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/v1/machines?'))).toBe(false)
  })

  it('renders a demo-mode label only when the backend says demo mode is active', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ ...localOverview, demo_mode: true })))
    renderPage()
    expect(await screen.findByText('Demo mode')).toBeInTheDocument()
  })

  it('renders authoritative zero counts rather than placeholders', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      ...localOverview,
      unresolved_incident_count: 0,
      counts: { ...localOverview.counts, components: 0, evidence: 0, incidents: 0 },
      return_to_service: { ...localOverview.return_to_service, state: 'CLEARED', blocking_reasons: [] },
    })))
    renderPage()
    await screen.findByText('CLEARED')
    expect(screen.getAllByText('0', { selector: '.metric-card__value' })).toHaveLength(4)
    expect(screen.getByText('No blocking reasons')).toBeInTheDocument()
  })

  it('does not infer connectivity when transport has not been measured', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response(localOverview)))
    renderPage()
    expect((await screen.findAllByText('Not yet measured')).length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText(/^Online$/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Synchronized$/i)).not.toBeInTheDocument()
  })

  it('shows loading and error states without fabricating local values', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    const view = renderPage()
    expect(screen.getByRole('status', { name: 'Local machine overview loading' })).toBeInTheDocument()
    view.unmount()

    vi.stubGlobal('fetch', vi.fn(() => response({ error: { code: 'TEST_ERROR', message: 'failed' } }, 500)))
    renderPage()
    expect(await screen.findByText('This Machine unavailable')).toBeInTheDocument()
  })
})
