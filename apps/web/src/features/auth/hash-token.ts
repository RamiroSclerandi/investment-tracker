// TanStack's location.hash omits the '#'; a raw window.location.hash keeps it. Accept both.
export function tokenFromHash(hash: string): string | null {
  return new URLSearchParams(hash.replace(/^#/, '')).get('token')
}
