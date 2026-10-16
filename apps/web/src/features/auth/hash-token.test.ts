import { describe, expect, it } from 'vitest'
import { hashParams, tokenFromHash } from '@/features/auth/hash-token'

describe('hashParams', () => {
  it('reads parameters whether or not the hash keeps its leading #', () => {
    expect(hashParams('#error=oauth_failed').get('error')).toBe('oauth_failed')
    expect(hashParams('error=oauth_failed').get('error')).toBe('oauth_failed')
  })
})

describe('tokenFromHash', () => {
  it('reads the token when the hash keeps its leading #', () => {
    expect(tokenFromHash('#token=aB-_9xY0zQ')).toBe('aB-_9xY0zQ')
  })

  it('reads the token when the hash has no leading #', () => {
    expect(tokenFromHash('token=aB-_9xY0zQ')).toBe('aB-_9xY0zQ')
  })

  it('returns null when the hash carries no token', () => {
    expect(tokenFromHash('')).toBeNull()
    expect(tokenFromHash('#error=oauth_failed')).toBeNull()
  })
})
