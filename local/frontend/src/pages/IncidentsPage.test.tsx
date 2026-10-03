// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentsPage } from './IncidentsPage'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

const machine = { id: 'machine-001', display_name: 'Truck One', asset_code: null, machine_type: null, manufacturer: null, model: null, site_name: null, site_area: null }
const incident = { incident_id: 'incident-001', machine_id: 'machine-001', status: 'OPEN', severity: null, owner_ref: null, due_state: null, due_time: null, created_at: null, updated_at: '2026-10-03T01:00:00Z' }

function LocationProbe() { const location = useLocation(); return <output data-testid="location">{location.search}</output> }
function renderPage(initialEntry = '/incidents') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initialEntry]}><Routes><Route path="/incidents" element={<><IncidentsPage /><LocationProbe /></>} /></Routes></MemoryRouter></QueryClientProvider>)
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('IncidentsPage local-machine scope', () => {
  it('ignores any browser machine_id filter and scopes the backend request to /machines/current identity', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/machines/current') return jsonResponse(machine)
      if (url.startsWith('/api/v1/incidents?')) return jsonResponse({ items: [], total: 0, offset: 20, limit: 20 })
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage('/incidents?offset=20&limit=20&machine_id=machine-foreign&status=OPEN&severity=HIGH&owner_ref=ops&due_state=OVERDUE')

    await screen.findByText('No incidents found')
    const incidentUrl = fetchMock.mock.calls.map(([input]) => String(input)).find((url) => url.startsWith('/api/v1/incidents?'))
    expect(incidentUrl).toContain('machine_id=machine-001')
    expect(incidentUrl).not.toContain('machine-foreign')
    expect(screen.queryByLabelText(/Machine ID/i)).not.toBeInTheDocument()
  })

  it('preserves local incident filters when paginating without adding a machine selector to the URL', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/machines/current') return jsonResponse(machine)
      if (url.startsWith('/api/v1/incidents?')) return jsonResponse({ items: [incident], total: 30, offset: 0, limit: 10 })
      return jsonResponse({}, 404)
    }))
    renderPage('/incidents?offset=0&limit=10&status=OPEN')
    await screen.findByText('Truck One')
    fireEvent.click(screen.getByRole('button', { name: /Next/i }))
    await waitFor(() => expect(screen.getByTestId('location').textContent).toContain('offset=10'))
    expect(screen.getByTestId('location').textContent).toContain('status=OPEN')
    expect(screen.getByTestId('location').textContent).not.toContain('machine_id=')
  })

  it('shows loading while configured identity is unresolved', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    renderPage()
    expect(screen.getAllByRole('status', { name: 'Incidents loading' })).toHaveLength(6)
  })

  it('shows an incident API error after configured identity succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => String(input) === '/api/v1/machines/current' ? jsonResponse(machine) : jsonResponse({ error: { code: 'SERVER_ERROR', message: 'No' } }, 500)))
    renderPage()
    expect(await screen.findByText('Incidents unavailable')).toBeInTheDocument()
  })

  it('refuses a backend incident belonging to another machine instead of switching context', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/machines/current') return jsonResponse(machine)
      if (url.startsWith('/api/v1/incidents?')) return jsonResponse({ items: [{ ...incident, machine_id: 'machine-foreign' }], total: 1, offset: 0, limit: 25 })
      return jsonResponse({}, 404)
    }))
    renderPage()
    expect(await screen.findByText('Machine-scope violation')).toBeInTheDocument()
    expect(screen.queryByText('machine-foreign')).not.toBeInTheDocument()
  })
})
