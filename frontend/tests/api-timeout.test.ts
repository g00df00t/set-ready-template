/* A request that never answers gives up, so the button that sent it resets.
 *
 *   cd frontend && node --experimental-strip-types tests/api-timeout.test.ts
 */

import { TimeoutError, withTimeout } from "../src/lib/timeout.ts";

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  — " + detail}`);
  if (!ok) FAILS.push(name);
}

// Stands in for fetch: never settles on its own, rejects the way the browser
// does once its signal aborts — or at once, if it already has.
function hang(signal: AbortSignal): Promise<string> {
  return new Promise((_, reject) => {
    const abort = () => reject(new DOMException("aborted", "AbortError"));
    if (signal.aborted) abort();
    signal.addEventListener("abort", abort);
  });
}

async function caught(p: Promise<unknown>): Promise<unknown> {
  try { await p; return null; } catch (err) { return err; }
}

const fast = await withTimeout(1000, null, false, async () => "ok");
check("an answer inside the limit comes back", fast === "ok");

let err = await caught(withTimeout(20, null, false, hang));
check("a hung read becomes a TimeoutError", err instanceof TimeoutError, String(err));
check("…not named AbortError, which callers ignore", (err as Error)?.name === "TimeoutError");
check("…saying to check the connection", /connection/.test((err as Error)?.message));

err = await caught(withTimeout(20, null, true, hang));
check("a hung write says it may have saved", /may still have saved/.test((err as Error)?.message), String(err));

const ctrl = new AbortController();
setTimeout(() => ctrl.abort(), 10);
err = await caught(withTimeout(1000, ctrl.signal, true, hang));
check("the caller's own cancel stays an AbortError", (err as Error)?.name === "AbortError", String(err));

const already = new AbortController();
already.abort();
err = await caught(withTimeout(1000, already.signal, false, hang));
check("an already-cancelled signal aborts at once", (err as Error)?.name === "AbortError", String(err));

err = await caught(withTimeout(1000, null, false, async () => { throw new Error("400 nope"); }));
check("the server's own error passes through untouched", (err as Error)?.message === "400 nope");

// Nothing left pending: if a timer leaked, the 60s one below would hold the
// process open and the test would visibly hang.
await withTimeout(60_000, null, false, async () => "done");

console.log(FAILS.length ? `\nFAIL: ${FAILS.length} failed` : "\nPASS: all api-timeout checks");
if (FAILS.length) process.exit(1);
