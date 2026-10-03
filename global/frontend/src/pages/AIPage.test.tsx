// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AIPage } from './AIPage'

function renderPage() { const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } }); return render(<QueryClientProvider client={client}><MemoryRouter><AIPage /></MemoryRouter></QueryClientProvider>) }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('AIPage', () => {
  it('does not call Groq until Run Analysis and renders evidence citations', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ state: 'AVAILABLE', provider: 'groq', model: 'test', summary: 'Fleet summary', claims: [], limitations: [], citations: [{ evidence_id: 'evidence-01', provenance: { source: 'edge' } }] }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    vi.stubGlobal('fetch', fetchMock); renderPage(); expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Analysis request'), { target: { value: 'Compare incidents' } }); expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Run Analysis' }))
    expect(await screen.findByText('Fleet summary')).toBeInTheDocument(); expect(screen.getByText('evidence-01')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  })

  it('shows Groq degraded response without hiding canonical-read-only messaging', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ state: 'DEGRADED', provider: 'groq', reason: 'missing_groq_api_key', citations: [], claims: [], limitations: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))))
    renderPage(); fireEvent.change(screen.getByLabelText('Analysis request'), { target: { value: 'Summarize' } }); fireEvent.click(screen.getByRole('button', { name: 'Run Analysis' }))
    expect(await screen.findByText('missing_groq_api_key')).toBeInTheDocument()
  })
})
