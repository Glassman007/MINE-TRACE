// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AddEvidencePage } from './AddEvidencePage'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

const machine = {
  id: 'machine-01',
  display_name: 'Haul Truck Alpha',
  asset_code: 'HT-01',
  machine_type: 'HAUL_TRUCK',
  manufacturer: 'MineCo',
  model: 'HX',
  site_name: 'North Pit',
  site_area: 'Bench 2',
}

const components = [
  {
    id: 'component-01',
    machine_id: 'machine-01',
    display_name: 'Brake Assembly',
    component_type: 'BRAKE',
    manufacturer: null,
    model: null,
  },
]

function installApi(response = { evidence_id: 'evidence-01', idempotent_replay: false }) {
  const posts: Array<{ url: string; body: Record<string, unknown> }> = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (method === 'GET' && url === '/api/v1/machines/current') return jsonResponse(machine)
    if (method === 'GET' && url === '/api/v1/machines/current/components') return jsonResponse({ machine_id: 'machine-01', components })
    if (method === 'POST' && url.startsWith('/api/v1/evidence/')) {
      posts.push({ url, body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> })
      return jsonResponse(response)
    }
    return jsonResponse({ error: { code: 'NOT_FOUND', message: `Unexpected ${method} ${url}` } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, posts }
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/evidence/new']}>
        <Routes><Route path="/evidence/new" element={<AddEvidencePage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function chooseMachine(includeComponent = false) {
  await screen.findByText('Haul Truck Alpha')
  await screen.findByRole('option', { name: 'Brake Assembly' })
  if (includeComponent) fireEvent.change(screen.getByLabelText(/Component/i), { target: { value: 'component-01' } })
}

function fillCommon(sourceLabel: RegExp, sourceValue: string) {
  fireEvent.change(screen.getByLabelText(/Original source record ID/i), { target: { value: 'source-record-01' } })
  fireEvent.change(screen.getByLabelText(/Original timestamp/i), { target: { value: '2026-10-03T08:30' } })
  fireEvent.change(screen.getByLabelText(sourceLabel), { target: { value: sourceValue } })
  fireEvent.change(screen.getByLabelText(/^Payload/i), { target: { value: '{"normalized":true}' } })
  fireEvent.change(screen.getByLabelText(/^Raw payload/i), { target: { value: '{"raw":42}' } })
  fireEvent.change(screen.getByLabelText(/^Provenance/i), { target: { value: '{"source":"edge-gateway"}' } })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AddEvidencePage ingestion modes', () => {
  it('submits a machine event with API-selected machine/component and parsed JSON', async () => {
    const { posts } = installApi()
    renderPage()
    await chooseMachine(true)
    fillCommon(/Event type/i, 'PRESSURE_WARNING')

    fireEvent.click(screen.getByRole('button', { name: 'Record evidence' }))

    expect(await screen.findByText('Evidence recorded')).toBeInTheDocument()
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toBe('/api/v1/evidence/machine-events')
    expect(posts[0].body).toMatchObject({
      machine_id: 'machine-01',
      component_id: 'component-01',
      original_source_record_id: 'source-record-01',
      event_type: 'PRESSURE_WARNING',
      payload: { normalized: true },
      raw_payload: { raw: 42 },
      provenance: { source: 'edge-gateway' },
    })
    expect(posts[0].body).not.toHaveProperty('source_type')
    expect(screen.getByRole('link', { name: /Open evidence in machine timeline/i })).toHaveAttribute('href', '/machines/machine-01#evidence-evidence-01')
  })

  it('submits a maintenance record using record_type rather than a frontend vocabulary', async () => {
    const { posts } = installApi()
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /Maintenance Record/i }))
    await chooseMachine()
    fillCommon(/Record type/i, 'HYDRAULIC_INSPECTION')

    fireEvent.click(screen.getByRole('button', { name: 'Record evidence' }))
    await waitFor(() => expect(posts).toHaveLength(1))

    expect(posts[0].url).toBe('/api/v1/evidence/maintenance-records')
    expect(posts[0].body).toMatchObject({ machine_id: 'machine-01', record_type: 'HYDRAULIC_INSPECTION' })
    expect(posts[0].body).not.toHaveProperty('event_type')
    expect(posts[0].body).not.toHaveProperty('source_type')
  })

  it('submits a human observation and treats idempotent replay as a successful reuse', async () => {
    const { posts } = installApi({ evidence_id: 'evidence-existing', idempotent_replay: true })
    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /Human Observation/i }))
    await chooseMachine()
    fillCommon(/Observation type/i, 'OPERATOR_NOTE')

    fireEvent.click(screen.getByRole('button', { name: 'Record evidence' }))

    expect(await screen.findByText('Existing evidence reused — duplicate source record was not created again')).toBeInTheDocument()
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toBe('/api/v1/evidence/human-observations')
    expect(posts[0].body).toMatchObject({ observation_type: 'OPERATOR_NOTE' })
  })
})

describe('AddEvidencePage validation and optional structures', () => {
  it('loads component choices from the configured-machine endpoint', async () => {
    const { fetchMock } = installApi()
    renderPage()
    await chooseMachine()

    expect(screen.getByRole('option', { name: 'Brake Assembly' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/v1/machines/current/components')).toBe(true)
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/v1/machines?'))).toBe(false)
  })

  it('rejects invalid JSON before sending any ingestion request', async () => {
    const { posts } = installApi()
    renderPage()
    await chooseMachine()
    fillCommon(/Event type/i, 'FAULT')
    fireEvent.change(screen.getByLabelText(/^Payload/i), { target: { value: '{invalid' } })

    fireEvent.click(screen.getByRole('button', { name: 'Record evidence' }))

    expect(await screen.findByText(/Invalid JSON/i)).toBeInTheDocument()
    expect(posts).toHaveLength(0)
  })

  it.each([
    ['Machine Event', /Event type/i],
    ['Maintenance Record', /Record type/i],
    ['Human Observation', /Observation type/i],
  ])('requires the source-specific string for %s', async (tabName, expectedLabel) => {
    const { posts } = installApi()
    renderPage()
    if (tabName !== 'Machine Event') fireEvent.click(screen.getByRole('tab', { name: new RegExp(tabName, 'i') }))
    await chooseMachine()
    fireEvent.change(screen.getByLabelText(/Original source record ID/i), { target: { value: 'source-1' } })
    fireEvent.change(screen.getByLabelText(/Original timestamp/i), { target: { value: '2026-10-03T08:30' } })

    fireEvent.click(screen.getByRole('button', { name: 'Record evidence' }))

    const sourceInput = screen.getByLabelText(expectedLabel)
    expect(sourceInput).toHaveAttribute('aria-invalid', 'true')
    expect(await screen.findByText(/is required/i)).toBeInTheDocument()
    expect(posts).toHaveLength(0)
  })

  it('submits all five context dimensions with value, quality, and freshness_basis', async () => {
    const { posts } = installApi()
    renderPage()
    await chooseMachine()
    fillCommon(/Event type/i, 'TEMPERATURE_WARNING')

    fireEvent.click(screen.getByLabelText(/Include context snapshot/i))
    const qualityFields = screen.getAllByLabelText(/^Quality$/i)
    const valueFields = screen.getAllByLabelText(/^Value$/i)
    const freshnessFields = screen.getAllByLabelText(/^Freshness basis$/i)
    expect(qualityFields).toHaveLength(5)
    expect(valueFields).toHaveLength(5)
    expect(freshnessFields).toHaveLength(5)

    fireEvent.change(qualityFields[0], { target: { value: 'KNOWN' } })
    fireEvent.change(valueFields[0], { target: { value: 'Shift A' } })
    freshnessFields.forEach((field, index) => fireEvent.change(field, { target: { value: `basis-${index}` } }))

    fireEvent.click(screen.getByRole('button', { name: 'Record evidence' }))
    await waitFor(() => expect(posts).toHaveLength(1))

    const snapshot = posts[0].body.context_snapshot as Record<string, Record<string, unknown>>
    expect(Object.keys(snapshot)).toEqual(['shift', 'location', 'machine_operating_state', 'workload', 'environment'])
    expect(snapshot.shift).toEqual({ value: 'Shift A', quality: 'KNOWN', freshness_basis: 'basis-0' })
    expect(snapshot.location).toEqual({ value: null, quality: 'UNKNOWN', freshness_basis: 'basis-1' })
  })

  it('submits attachment metadata only and exposes no binary file input', async () => {
    const { posts } = installApi()
    renderPage()
    await chooseMachine()
    fillCommon(/Event type/i, 'FAULT')

    fireEvent.click(screen.getByRole('button', { name: /Add metadata/i }))
    const metadataCard = screen.getByText('Metadata record 1').closest('.attachment-form-card')
    expect(metadataCard).not.toBeNull()
    const scope = within(metadataCard as HTMLElement)
    fireEvent.change(scope.getByLabelText(/Attachment type/i), { target: { value: 'AUDIO_REFERENCE' } })
    fireEvent.change(scope.getByLabelText(/Storage reference/i), { target: { value: 'edge://evidence/audio-1' } })
    fireEvent.change(scope.getByLabelText(/MIME type/i), { target: { value: 'audio/wav' } })
    fireEvent.change(scope.getByLabelText(/File size/i), { target: { value: '2048' } })
    fireEvent.change(scope.getByLabelText(/Checksum/i), { target: { value: 'sha256:abc' } })
    fireEvent.change(scope.getByLabelText(/Created at/i), { target: { value: '2026-10-03T08:31' } })

    expect(document.querySelector('input[type="file"]')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Record evidence' }))
    await waitFor(() => expect(posts).toHaveLength(1))

    expect(posts[0].body.attachments).toEqual([
      expect.objectContaining({
        attachment_type: 'AUDIO_REFERENCE',
        storage_reference: 'edge://evidence/audio-1',
        mime_type: 'audio/wav',
        file_size: 2048,
        checksum: 'sha256:abc',
      }),
    ])
  })
})
