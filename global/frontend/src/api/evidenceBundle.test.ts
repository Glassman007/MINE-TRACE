// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getEvidenceBundle } from './evidenceBundle'

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('Evidence Bundle API', () => {
  it('loads the deterministic bundle from the authoritative incident endpoint', async () => {
    const fetchMock = vi.fn(() => response({
      status: 'READY',
      primary_incident_evidence: [],
      selected_exact_history: [],
      selected_semantic_history: [],
      verification_context: null,
      evidence_time_context_snapshots: [],
      provenance_index: {},
      completeness: {},
    }))
    vi.stubGlobal('fetch', fetchMock)

    const bundle = await getEvidenceBundle('incident-1')

    expect(bundle.status).toBe('READY')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/incidents/incident-1/evidence-bundle', expect.objectContaining({ method: 'GET' }))
  })
})
