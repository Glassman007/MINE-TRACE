/** Presentation-only schematic metadata. Never used as canonical machine state. */
export const demoComponentSchematic: Record<string, { x: number; y: number }> = {
  ENGINE: { x: 20, y: 48 },
  HYDRAULIC_PUMP: { x: 34, y: 58 },
  BOOM: { x: 56, y: 26 },
  ARM: { x: 70, y: 34 },
  BUCKET: { x: 84, y: 62 },
  COOLING_SYSTEM: { x: 18, y: 30 },
  FINAL_DRIVE: { x: 38, y: 80 },
}

export const demoSemanticQuery = 'hydraulic pump pressure slow response whine'
