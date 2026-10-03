import { describe, expect, it } from 'vitest'
import * as incidents from './incidents'

describe('global incident API authority boundary', () => {
  it('does not export local-authority mutation wrappers', () => {
    for (const forbidden of [
      'moveIncidentEvidence',
      'splitIncident',
      'startIncidentVerification',
      'evaluateDueVerifications',
      'addEvidence',
      'createHandover',
    ]) {
      expect(forbidden in incidents).toBe(false)
    }
  })
})
