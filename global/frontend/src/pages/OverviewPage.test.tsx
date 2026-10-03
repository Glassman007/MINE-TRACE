// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OverviewPage } from './OverviewPage'

function renderOverview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><OverviewPage /></MemoryRouter></QueryClientProvider>)
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Fleet OverviewPage', () => {
  it('renders only backend-derived fleet fields and synchronized sessions', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      fleet_machine_count: 12,
      unresolved_incident_count: 4,
      verification_states: { SUCCEEDED: 3 },
      latest_sync_received_at: '2026-10-03T08:00:00Z',
      latest_acknowledged_at: '2026-10-03T08:01:00Z',
      acknowledgement_status_counts: { ACCEPTED: 10 },
      unresolved_sync_conflicts: 2,
      recent_sessions: [{
        session_id: 'session-1', machine_id: 'machine-1', started_at: '2026-10-03T07:00:00Z', ended_at: '2026-10-03T08:00:00Z',
        state: 'CLOSED', operating_hours: 1, latest_report_revision: 2, ingested_at: '2026-10-03T08:00:00Z', updated_at: '2026-10-03T08:00:00Z',
      }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))))

    renderOverview()

    expect(await screen.findByText('12')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('CLOSED')).toBeInTheDocument()
    expect(screen.getByText(/Revision 2/)).toBeInTheDocument()
    expect(screen.queryByText(/fleet health/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/productivity/i)).not.toBeInTheDocument()
  })

  it('shows an explicit empty session state without fabricating machines', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      fleet_machine_count: 0, unresolved_incident_count: 0, verification_states: {}, latest_sync_received_at: null,
      latest_acknowledged_at: null, acknowledgement_status_counts: {}, unresolved_sync_conflicts: 0, recent_sessions: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))))
    renderOverview()
    expect(await screen.findByText('No sessions')).toBeInTheDocument()
  })
})
