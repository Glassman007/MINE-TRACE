// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MachinesPage } from './MachinesPage'

function response(body: unknown) { return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })) }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('MachinesPage', () => {
  it('uses site/type/model filters and renders backend last sync', async () => {
    const fetchMock = vi.fn(() => response({ items: [{ id: 'm-1', display_name: 'Truck One', asset_code: 'HT-01', machine_type: 'HAUL_TRUCK', manufacturer: 'Maker', model: 'MT-100', site_name: 'North', site_area: null, latest_sync_received_at: '2026-10-03T08:00:00Z', latest_acknowledged_at: '2026-10-03T08:01:00Z', latest_acknowledgement_status: 'ACCEPTED', latest_report_revision: 2 }], total: 1, offset: 0, limit: 12 }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/machines?site=North&machine_type=HAUL_TRUCK&model=MT-100']}><Routes><Route path="/machines" element={<MachinesPage />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('Truck One')).toBeInTheDocument()
    expect(screen.getByText('Last sync')).toBeInTheDocument()
    const url = new URL(String(fetchMock.mock.calls[0]?.[0]), 'http://mine-trace.test')
    expect(url.searchParams.get('site')).toBe('North'); expect(url.searchParams.get('machine_type')).toBe('HAUL_TRUCK'); expect(url.searchParams.get('model')).toBe('MT-100')
  })
})
