// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AnalyticsPage } from './AnalyticsPage'

function response(body: unknown) { return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })) }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('AnalyticsPage', () => {
  it('renders relational analytics endpoints only', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/summary')) return response({ machines: 3, sessions: 4, incidents: 5, unresolved_incidents: 2, evidence: 8, maintenance_actions: 2, verification_runs: 1, completed_verification_runs: 1, verification_completion_rate: 1, sync_conflicts_unresolved: 1 })
      if (url.endsWith('/by-status')) return response({ items: [{ key: 'OPEN', count: 2 }] })
      if (url.endsWith('/by-site')) return response({ items: [{ key: 'North', count: 3 }] })
      return response({ items: [{ day: '2026-10-03', count: 2 }] })
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); render(<QueryClientProvider client={client}><MemoryRouter><AnalyticsPage /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('3')).toBeInTheDocument(); expect(screen.getByText('OPEN')).toBeInTheDocument(); expect(screen.getByText('North')).toBeInTheDocument(); expect(screen.queryByText(/similarity/i)).not.toBeInTheDocument()
  })
})
