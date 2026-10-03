export interface MachineArtwork {
  src: string
  alt: string
}

const machineArtworkRegistry: Array<{ matches: (normalizedType: string) => boolean; artwork: MachineArtwork }> = [
  {
    matches: (value) => value.includes('HAUL') && value.includes('TRUCK'),
    artwork: { src: '/machines/haul-truck.png', alt: 'Haul truck' },
  },
  {
    matches: (value) => value.includes('WHEEL') && value.includes('LOADER'),
    artwork: { src: '/machines/wheel-loader.png', alt: 'Wheel loader' },
  },
  {
    matches: (value) => value.includes('EXCAVATOR'),
    artwork: { src: '/machines/excavator.svg', alt: 'Excavator' },
  },
]

export function artworkForMachineType(machineType: string | null | undefined): MachineArtwork | null {
  if (!machineType) return null
  const normalized = machineType.trim().toUpperCase().replace(/[_-]+/g, ' ')
  return machineArtworkRegistry.find((entry) => entry.matches(normalized))?.artwork ?? null
}
