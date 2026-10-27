// Shared time parsing/formatting for schedule, crew, and talent pages.
//
// Values returned by the API are normalized 24h "HH:MM:SS", but a user may
// type a 12h value like "8:00 PM" into an input. parseTime handles both — it
// is AM/PM aware, so a stray "PM" is never silently dropped.

/** Minutes since midnight, or NaN if unparseable. AM/PM aware. */
export function timeToMins(t: string): number {
  const m = t.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?/);
  if (!m) return NaN;
  let h = parseInt(m[1], 10);
  const min = parseInt(m[2], 10);
  const ap = m[3]?.toUpperCase();
  if (ap === "PM" && h < 12) h += 12;
  if (ap === "AM" && h === 12) h = 0;
  return h * 60 + min;
}

/** Minutes since midnight back to 24h "HH:MM", wrapping across midnight. */
export function minsToTime(mins: number): string {
  const wrapped = ((mins % 1440) + 1440) % 1440;
  const h = Math.floor(wrapped / 60);
  const m = wrapped % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Human-facing "8:00 PM". Returns the input unchanged if it can't be parsed. */
export function fmt(t: string): string {
  const mins = timeToMins(t);
  if (isNaN(mins)) return t;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
}

/** Shift a time by some minutes, returning 24h "HH:MM". Unparseable -> unchanged. */
export function addMinutes(time: string, mins: number): string {
  const base = timeToMins(time);
  if (isNaN(base)) return time;
  return minsToTime(base + mins);
}

/**
 * Named call times a producer can use instead of a clock time — heads of
 * department who set their own call, a stylist who reports when the truck
 * lands, a client who's TBD until the day before. Mirrors the closed set the
 * API accepts (backend/time_utils.py); typing anything else is still validated
 * as a time, so a typo'd "9:0O AM" is refused rather than printed on the sheet.
 */
export const CALL_TIME_LABELS = [
  "Own Call", "Own Time", "Self Report", "TBD", "Hold", "As Needed", "On Call", "N/A",
];

/** What a person's call-time field should show: their named call if they have
 *  one, otherwise their formatted clock time, otherwise empty. */
export function callTimeValue(p: { call_time: string | null; call_time_note?: string | null }): string {
  return p.call_time_note || (p.call_time ? fmt(p.call_time) : "");
}

/**
 * The API's reason, if what it refused was a *time* field — otherwise null.
 *
 * FastAPI returns a single `detail` string for these, with no field name to key
 * on, so this matches the sentence `backend/time_utils.py` raises. Keep the two
 * in sync. If that wording ever changes this stops highlighting the field and
 * the message falls back to the form-level banner, which is the safe direction
 * to fail — the producer still sees why, just not where.
 */
export function timeError(err: unknown): string | null {
  return refusedTime(err) === null ? null : (err as Error).message;
}

/** The text the API refused, or null if this wasn't a time complaint. */
function refusedTime(err: unknown): string | null {
  const message = err instanceof Error ? err.message : "";
  const match = /^"(.*)" isn't a valid time/.exec(message);
  return match ? match[1] : null;
}

/**
 * Like `timeError`, but only when the refused text is what's in *this* field.
 *
 * A form with a start and an end time would otherwise light up both on one bad
 * value. The backend quotes the offending input back, so comparing against it
 * tells us which of the two the producer actually mistyped.
 */
export function timeErrorFor(err: unknown, value: string): string | null {
  const refused = refusedTime(err);
  return refused !== null && refused === value.trim() ? (err as Error).message : null;
}
