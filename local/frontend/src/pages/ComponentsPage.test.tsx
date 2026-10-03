// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ComponentsPage } from './ComponentsPage'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

const machine = { id: 'machine-01', display_name: 'Haul Truck Alpha', asset_code: 'HT-01', machine_type: 'HAUL_TRUCK', manufacturer: null, model: null, site_name: null, site_area: null }
const component = { id: 'component-01', machine_id: 'machine-01', display_name: 'Brake Assembly', component_type: 'BRAKE', manufacturer: null, model: null }

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><ComponentsPage /></MemoryRouter></QueryClientProvider>)
}

function installApi(components: unknown[] = [component], componentStatus = 200) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/v1/machines/current') return jsonResponse(machine)
    if (url === '/api/v1/machines/current/components') {
      return componentStatus === 200
        ? jsonResponse({ machine_id: machine.id, components })
        : jsonResponse({ error: { code: 'COMPONENTS_UNAVAILABLE', message: 'down' } }, componentStatus)
    }
    return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${url}` } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('ComponentsPage', () => {
  it('renders backend-returned components as schematic navigation without inventing status', async () => {
    installApi()
    renderPage()
    const link = await screen.findByRole('link', { name: /Brake Assembly/i })
    expect(link).toHaveAttribute('href', '/components/component-01')
    expect(screen.getByText(/layout does not claim physically accurate placement/i)).toBeInTheDocument()
    expect(screen.queryByText(/healthy|critical|warning/i)).not.toBeInTheDocument()
  })


  it('rejects a foreign-machine component returned by the current-machine endpoint', async () => {
    installApi([{ ...component, machine_id: 'machine-foreign' }])
    renderPage()
    expect(await screen.findByText('Machine-scope violation')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Brake Assembly/i })).not.toBeInTheDocument()
  })

  it('shows an explicit empty state when the backend returns no components', async () => {
    installApi([])
    renderPage()
    expect(await screen.findByText('No components returned')).toBeInTheDocument()
  })

  it('shows a degraded component state while preserving configured machine identity', async () => {
    installApi([], 503)
    renderPage()
    expect(await screen.findByText('Haul Truck Alpha')).toBeInTheDocument()
    expect(await screen.findByText('Components unavailable')).toBeInTheDocument()
  })


  it('uses centralized demo schematic coordinates only when backend demo mode is true', async () => {
    const demoMachine = { ...machine, display_name: 'EXC-204', asset_code: 'EXC-204', machine_type: 'Hydraulic Excavator' }
    const demoComponents = [
      { ...component, id: 'component-engine', machine_id: demoMachine.id, display_name: 'Engine', component_type: 'ENGINE' },
      { ...component, id: 'component-pump', machine_id: demoMachine.id, display_name: 'Hydraulic Pump', component_type: 'HYDRAULIC_PUMP' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/machines/current') return jsonResponse(demoMachine)
      if (url === '/api/v1/machines/current/components') return jsonResponse({ machine_id: demoMachine.id, components: demoComponents })
      if (url === '/api/v1/overview') return jsonResponse({ demo_mode: true, machine: demoMachine, active_session: null, operating_state: null, unresolved_incident_count: 0, counts: { components: 2, evidence: 0, incidents: 0, incidents_by_status: {} }, return_to_service: { state: 'CLEARED', blocking_reasons: [], policy_identifier: 'demo', policy_revision: 1 }, sync: { transport_configured: false, transport_available: null, transport_checked_at: null, latest_package_state: null, last_acknowledgement: null, last_error: null } })
      return jsonResponse({}, 404)
    }))
    renderPage()
    const engine = await screen.findByRole('link', { name: /Engine/i })
    expect(engine).toHaveClass('demo-schematic__node')
    expect(engine).toHaveStyle({ left: '20%', top: '48%' })
    expect(screen.queryByText(/healthy|critical|warning/i)).not.toBeInTheDocument()
  })

  it('shows loading state while backend identity/component requests are pending', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    renderPage()
    expect(screen.getByRole('status', { name: 'Configured machine loading' })).toBeInTheDocument()
    expect(screen.getAllByRole('status', { name: 'Components loading' })).toHaveLength(2)
  })
})
