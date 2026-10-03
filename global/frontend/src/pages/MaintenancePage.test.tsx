// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MaintenancePage } from './MaintenancePage'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('MaintenancePage', () => {
  it('renders canonical queue fields without predictive priority', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ items: [{ incident_id: 'i-1', machine_id: 'm-1', component_id: null, incident_status: 'OPEN', due_state: 'DUE', due_time: null, latest_maintenance_action_id: null, latest_maintenance_action_type: null, latest_maintenance_at: null, latest_verification_run_id: null, latest_verification_result: null, latest_verification_completed_at: null, verification_required: true, machine_model: 'MT-100', site_name: 'North', updated_at: '2026-10-03T08:00:00Z' }], total: 1, offset: 0, limit: 25, ordering: 'due_time,state,updated_at' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter><MaintenancePage /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('OPEN')).toBeInTheDocument(); expect(screen.getByText('Required')).toBeInTheDocument(); expect(screen.queryByText(/risk score|predictive priority/i)).not.toBeInTheDocument()
  })
})
