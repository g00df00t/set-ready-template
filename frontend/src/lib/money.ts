/* Money as the budget and PC log speak it: INTEGER CENTS over the API, so no
 * float ever reaches a total (backend services/budget.py). This file only
 * converts at the edges — typing in, showing out — and never adds anything
 * up: every total comes from the API.
 */

/** $1,234.56 — always two places, as on a ledger. Matches backend pc_log.dollars(). */
export function formatCents(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(Math.round(cents));
  const whole = Math.floor(abs / 100).toLocaleString("en-US");
  return `${sign}$${whole}.${String(abs % 100).padStart(2, "0")}`;
}

/** What goes back in an input to edit: "1234.56", "" for nothing. */
export function centsToInput(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

/** Typed dollars to exact cents, by string arithmetic — "1,300.5" is 130050,
 * never 130049.99999. Blank is null; anything that isn't an amount is undefined. */
export function parseCents(text: string): number | null | undefined {
  const t = text.replace(/[$,\s]/g, "");
  if (t === "") return null;
  const m = /^(\d+)(?:\.(\d{0,2}))?$/.exec(t);
  if (!m) return undefined;
  const cents = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return cents <= 1_000_000_000 ? cents : undefined;
}

/** "8" or "7.5" (percent) to basis points; undefined if it isn't one. */
export function parseBp(text: string): number | undefined {
  const t = text.replace(/[%\s]/g, "");
  const m = /^(\d{1,3})(?:\.(\d{0,2}))?$/.exec(t);
  if (!m) return undefined;
  const bp = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return bp <= 10_000 ? bp : undefined;
}

/** 800 → "8", 750 → "7.5". */
export function bpToPct(bp: number): string {
  return String(bp / 100);
}
