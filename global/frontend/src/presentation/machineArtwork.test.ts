import { describe, expect, it } from 'vitest'
import { artworkForMachineType } from './machineArtwork'

describe('machine artwork registry', () => {
  it('maps presentation art by machine type', () => {
    expect(artworkForMachineType('Haul Truck')?.src).toBe('/machines/haul-truck.png')
    expect(artworkForMachineType('WHEEL_LOADER')?.src).toBe('/machines/wheel-loader.png')
    expect(artworkForMachineType('Excavator')?.src).toBe('/machines/excavator.svg')
  })

  it('returns no artwork for unknown machine types so the UI can use a generic icon', () => {
    expect(artworkForMachineType('Continuous Miner')).toBeNull()
    expect(artworkForMachineType(null)).toBeNull()
  })
})
