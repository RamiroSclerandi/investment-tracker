export const REQUEST_TIMEOUT_MS = 10_000

// A timer-driven AbortController instead of AbortSignal.timeout, which fake timers in tests cannot drive.
export async function withTimeout<T>(
  send: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await send(controller.signal)
  } finally {
    clearTimeout(timer)
  }
}
