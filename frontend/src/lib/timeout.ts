/* Giving up on a request that never answers.
 *
 * Pulled out of api.ts so it can be tested without a browser or Supabase
 * (tests/api-timeout.test.ts). api.ts is the only caller.
 */

/** The server didn't answer within the time limit. Deliberately not named
 * "AbortError": callers treat that as "the user cancelled" and stay silent. */
export class TimeoutError extends Error {
  constructor(write: boolean) {
    super(
      write
        // The request may have reached the server and finished; only the
        // answer was lost. Say so, rather than inviting a blind second try.
        ? "The server didn't answer in time. It may still have saved — reload to check before trying again."
        : "The server didn't answer in time. Check your connection and try again."
    );
    this.name = "TimeoutError";
  }
}

/** Run `fn` with a signal that aborts after `ms`, or when the caller's own
 * signal does. A timeout surfaces as TimeoutError; the caller's abort still
 * surfaces as the browser's AbortError, so "cancelled" stays silent.
 * (Not AbortSignal.any/timeout — Safari only gained .any in 17.4.) */
export async function withTimeout<T>(
  ms: number, callerSignal: AbortSignal | null | undefined, write: boolean,
  fn: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, ms);
  const onAbort = () => ctrl.abort();
  if (callerSignal?.aborted) ctrl.abort();
  else callerSignal?.addEventListener("abort", onAbort);
  try {
    return await fn(ctrl.signal);
  } catch (err) {
    if (timedOut && !callerSignal?.aborted) throw new TimeoutError(write);
    throw err;
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", onAbort);
  }
}
