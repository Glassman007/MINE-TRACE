import { afterEach, describe, expect, it, vi } from 'vitest'
import { acknowledgeHandover, createHandover, getHandover } from './handover'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

const packet = {
  id: 'packet-01',
  created_at: '2026-10-03T01:00:00Z',
  acknowledged_at: null,
  items: [],
}

afterEach(() => vi.unstubAllGlobals())

describe('handover API', () => {
  it('creates a handover without inventing request filters or a request body', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/handovers')
      expect(init?.method).toBe('POST')
      expect(init?.body).toBeUndefined()
      return jsonResponse(packet)
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(createHandover()).resolves.toEqual(packet)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retrieves a known packet by ID and never calls a collection GET', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/handovers/packet-01')
      expect(init?.method).toBe('GET')
      return jsonResponse(packet)
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getHandover('packet-01')).resolves.toEqual(packet)
    expect(fetchMock.mock.calls.every(([input]) => String(input) !== '/api/v1/handovers')).toBe(true)
  })

  it('acknowledges a known packet with no fabricated actor payload', async () => {
    const acknowledged = { ...packet, acknowledged_at: '2026-10-03T01:05:00Z' }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/handovers/packet-01/acknowledge')
      expect(init?.method).toBe('POST')
      expect(init?.body).toBeUndefined()
      return jsonResponse(acknowledged)
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(acknowledgeHandover('packet-01')).resolves.toEqual(acknowledged)
  })
})
