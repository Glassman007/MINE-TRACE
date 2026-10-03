// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { router } from './router'

describe('global router contract', () => {
  it('keeps global routes and excludes local capture/handover routes', () => {
    const children = router.routes[0]?.children ?? []
    const paths = children.map((route) => route.index ? '/' : `/${route.path}`).filter((path) => path !== '/*')
    for (const expected of ['/', '/machines', '/machines/:machineId', '/incidents', '/incidents/:incidentId', '/maintenance', '/search', '/analytics', '/sync', '/sync/conflicts', '/ai']) expect(paths).toContain(expected)
    for (const forbidden of ['/evidence/new', '/handover', '/handover/:packetId']) expect(paths).not.toContain(forbidden)
  })
})
