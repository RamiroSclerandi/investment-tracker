// TanStack's location.hash omits the '#'; a raw window.location.hash keeps it. Accept both.
export function hashParams(hash: string): URLSearchParams {
  return new URLSearchParams(hash.replace(/^#/, ''))
}

export function tokenFromHash(hash: string): string | null {
  return hashParams(hash).get('token')
}
