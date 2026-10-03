// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { evaluateDueVerifications, moveIncidentEvidence, splitIncident, startIncidentVerification } from './incidents'

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('incident mutation API wrappers', () => {
  it('posts the authoritative move contract without inventing fields', async () => {
    const fetchMock = vi.fn(() => response({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    await moveIncidentEvidence({
      sourceIncidentId: 'source-1',
      evidenceId: 'evidence-1',
      targetIncidentId: 'target-1',
      reason: 'wrong association',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/incidents/source-1/evidence/evidence-1/move',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ target_incident_id: 'target-1', reason: 'wrong association' }),
      }),
    )
  })

  it('posts only evidence_ids and reason for split', async () => {
    const fetchMock = vi.fn(() => response({ new_incident_id: 'new-1' }))
    vi.stubGlobal('fetch', fetchMock)

    await splitIncident({ sourceIncidentId: 'source-1', evidenceIds: ['e-1', 'e-2'], reason: 'separate issue' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/incidents/source-1/split',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ evidence_ids: ['e-1', 'e-2'], reason: 'separate issue' }),
      }),
    )
  })

  it('starts verification and evaluates due only when explicitly invoked', async () => {
    const fetchMock = vi.fn(() => response({}))
    vi.stubGlobal('fetch', fetchMock)

    expect(fetchMock).not.toHaveBeenCalled()
    await startIncidentVerification('incident-1')
    await evaluateDueVerifications()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/incidents/incident-1/verification', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/verifications/evaluate-due', expect.objectContaining({ method: 'POST' }))
  })

  it('preserves structured 409 conflict codes', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ error: { code: 'VERIFICATION_STATE_CONFLICT', message: 'State changed' } }, 409)))

    await expect(startIncidentVerification('incident-1')).rejects.toMatchObject({
      status: 409,
      code: 'VERIFICATION_STATE_CONFLICT',
      message: 'State changed',
    })
  })
})
