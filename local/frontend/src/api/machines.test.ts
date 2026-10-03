// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getCurrentMachine, getCurrentMachineComponents, getMachineTimeline } from './machines'

function jsonResponse(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))
}

afterEach(() => vi.unstubAllGlobals())

describe('local machine API contracts', () => {
  it('reads configured identity from /machines/current rather than discovering a fleet', async () => {
    const fetchMock = vi.fn<typeof fetch>(() => jsonResponse({ id: 'machine-01', display_name: 'Local Machine' }))
    vi.stubGlobal('fetch', fetchMock)
    await getCurrentMachine()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/machines/current', expect.objectContaining({ method: 'GET' }))
  })

  it('reads configured-machine components from the explicit current endpoint', async () => {
    const fetchMock = vi.fn<typeof fetch>(() => jsonResponse({ machine_id: 'machine-01', components: [{ id: 'component-01', machine_id: 'machine-01' }] }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await getCurrentMachineComponents()
    expect(result[0].id).toBe('component-01')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/machines/current/components', expect.objectContaining({ method: 'GET' }))
  })

  it('sends component and timezone-aware filters to exact timeline and preserves backend order', async () => {
    const fetchMock = vi.fn<typeof fetch>(() => jsonResponse({
      machine_id: 'machine/with spaces',
      component_id: 'component-01',
      evidence: [
        { evidence_id: 'earlier', machine_id: 'machine/with spaces', component_id: 'component-01', source_type: 'MACHINE_EVENT', original_source_record_id: 'a', original_timestamp: '2026-10-02T01:00:00Z', ingestion_timestamp: '2026-10-02T01:00:01Z', canonical_event_type: 'A', canonical_payload: {}, raw_source_payload: {}, provenance: {}, context_snapshots: [], attachments: [] },
        { evidence_id: 'later', machine_id: 'machine/with spaces', component_id: 'component-01', source_type: 'MACHINE_EVENT', original_source_record_id: 'b', original_timestamp: '2026-10-02T02:00:00Z', ingestion_timestamp: '2026-10-02T02:00:01Z', canonical_event_type: 'B', canonical_payload: {}, raw_source_payload: {}, provenance: {}, context_snapshots: [], attachments: [] },
      ],
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getMachineTimeline('machine/with spaces', { component_id: 'component-01', from: '2026-10-02T05:30:00.000Z', to: '2026-10-02T09:45:00.000Z' })
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://mine-trace.test')
    expect(url.pathname).toBe('/api/v1/machines/machine%2Fwith%20spaces/timeline')
    expect(url.searchParams.get('component_id')).toBe('component-01')
    expect(result.map((item) => item.id)).toEqual(['earlier', 'later'])
  })
})
