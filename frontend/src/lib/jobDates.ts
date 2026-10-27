// A job's dates on the front end: formatting, and the small amount of shape
// checking the Crew & dates table needs while a producer is editing a cell.
//
// The model is backend/services/job_dates.py — read that file's own comment
// first. In one sentence: `crew_dates` (on the job) and `dates_override` (on a
// hire) are both { travel?, checkin?, prep?, shoot?, off?, wrap?, travel_out?:
// [first, last][] }, ISO date
// strings, a missing key means "same as crew" and an empty list means "none".
//
// Everything ABOUT a hire's actual dates — effective_dates, conflicts,
// dates_text — comes from the API (GET /jobs/{id}/hires already computes them,
// the same way the deal memo PDF does), so this module only formats and edits.
// It never recomputes a conflict; that would be a second copy of §6's rules
// that could drift from the one the backend enforces.

// The order a job happens in — backend DAY_TYPES exactly. Check-in (already
// in town, no travel) and Down day joined 2026-10-01 from the producer's answers.
export const DAY_TYPES = ["travel", "checkin", "prep", "shoot", "off", "wrap", "travel_out"] as const;
export type DayType = (typeof DAY_TYPES)[number];

// The five every job has a column for, and the two that only some people
// have — the Pre-production table gives those one shared "Other days" column
// rather than two mostly empty ones. Guided setup never asks for them.
export const CORE_TYPES: DayType[] = ["travel", "prep", "shoot", "wrap", "travel_out"];
export const OTHER_TYPES: DayType[] = ["checkin", "off"];

// The work a day label names — backend LABELLED_TYPES. A label prints after
// these lines on its date, never after a travel line that shares the date.
export const LABELLED_TYPES: DayType[] = ["prep", "shoot", "off", "wrap"];

// The producer's vocabulary, with wrap split from travel out (Patrick, 2026-09-28): a
// WRAP day is work — stylists packing up and shipping merchandise, returning
// unused props — while TRAVEL OUT is flying home. Matches backend LABELS
// exactly (services/job_dates.py).
export const LABELS: Record<DayType, string> = {
  travel: "Travel in",
  checkin: "Check-in",
  prep: "Prep/Scout",
  shoot: "Shoot day",
  off: "Down day",
  wrap: "Wrap day",
  travel_out: "Travel out",
};

// The deal memo's wording where it says more than the screen label — backend
// MEMO_LABELS exactly (checked by tests/date_line_cases.json).
export const MEMO_LABELS: Record<DayType, string> = {
  ...LABELS,
  checkin: "Check into hotel (no travel)",
  off: "Down day – ½ day rate",
};

export type Span = [string, string];
export type DatesByType = Partial<Record<DayType, Span[]>>;

function ordinal(day: number): string {
  if (day % 10 === 1 && day !== 11) return "st";
  if (day % 10 === 2 && day !== 12) return "nd";
  if (day % 10 === 3 && day !== 13) return "rd";
  return "th";
}

// ISO date strings are compared and sliced as strings throughout — never
// round-tripped through `new Date(iso)` for arithmetic, which parses a bare
// "yyyy-mm-dd" as UTC midnight and drifts a day in any zone west of it. A
// local midnight Date is only ever constructed here, for formatting.
function toLocalDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(iso: string, n: number): string {
  const d = toLocalDate(iso);
  d.setDate(d.getDate() + n);
  return toIso(d);
}

/** "2026-10-11" -> "Oct 11th". */
function shortDay(iso: string): string {
  const d = toLocalDate(iso);
  const month = d.toLocaleDateString("en-US", { month: "short" });
  return `${month} ${d.getDate()}${ordinal(d.getDate())}`;
}

function weekday(iso: string): string {
  return toLocalDate(iso).toLocaleDateString("en-US", { weekday: "short" });
}

/** "Oct 11th - Sun" for one day, "Oct 13th (Tue) – Oct 15th (Thu)" for a span —
 *  exactly what backend job_dates.format_span produces, and what the deal memo
 *  and the old deal-memos page's picker both already write. */
export function formatSpan(first: string, last: string): string {
  if (first === last) return `${shortDay(first)} - ${weekday(first)}`;
  return `${shortDay(first)} (${weekday(first)}) – ${shortDay(last)} (${weekday(last)})`;
}

export function formatLine(type: DayType, first: string, last: string): string {
  return `${formatSpan(first, last)} - ${MEMO_LABELS[type]}`;
}

/** The short on-screen form the Crew & dates table and calendar use — the
 *  mockup's format, deliberately not the deal memo's: "Sun, Oct 4" for one
 *  day, "Oct 7 → 10" within a month, "Oct 30 → Nov 2" across one. The PDF
 *  line (formatSpan/formatLine) is the one that must match the backend. */
export function displaySpan(first: string, last: string): string {
  const day = (iso: string, opts: Intl.DateTimeFormatOptions) => toLocalDate(iso).toLocaleDateString("en-US", opts);
  if (first === last) return day(first, { weekday: "short", month: "short", day: "numeric" });
  const end = first.slice(0, 7) === last.slice(0, 7)
    ? String(toLocalDate(last).getDate())
    : day(last, { month: "short", day: "numeric" });
  return `${day(first, { month: "short", day: "numeric" })} → ${end}`;
}

/** Number of calendar days a span covers, inclusive. */
export function spanDays(first: string, last: string): number {
  const a = toLocalDate(first).getTime();
  const b = toLocalDate(last).getTime();
  return Math.round((b - a) / 86400000) + 1;
}

/** One person's dates block, in the order the job happens — mirrors backend
 *  dates_block(). Used only for a live preview while editing; the value that
 *  actually prints on the PDF is always rendered server side. */
export function datesBlock(crewDates: DatesByType, override: DatesByType): string {
  const eff = effectiveDates(crewDates, override);
  const lines: [string, number, string][] = [];
  for (const t of DAY_TYPES) {
    for (const span of eff[t] ?? []) lines.push([span[0], DAY_TYPES.indexOf(t), formatLine(t, span[0], span[1])]);
  }
  lines.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1]));
  return lines.map(([, , line]) => line).join("\n");
}

/** "No travel in", "No prep", "No wrap day", "No travel out" — the button
 *  that records a crew as having none of a day type. */
export function noneLabel(type: DayType): string {
  return `No ${LABELS[type].split("/")[0].toLowerCase()}`;
}

/** The order job setup walks the crew's dates in: the shoot first, since
 *  every other date is suggested from it, then out from it. A wrap day comes
 *  last: it's usually only the stylists', so most crews answer "No wrap day"
 *  and give it to those people on their own rows. */
export const SETUP_ORDER: DayType[] = ["shoot", "travel_out", "travel", "prep", "wrap"];

/** The first crew date setup still has to ask about, or null once they're all
 *  answered. The shoot needs real dates. The others count as answered once set
 *  or recorded as none: an empty list, which is also what the deal memo reads
 *  as "no line for this type", so "none" costs nothing downstream. */
export function nextCrewType(crewDates: DatesByType): DayType | null {
  return SETUP_ORDER.find((t) => (t === "shoot" ? !(crewDates.shoot ?? []).length : !(t in crewDates))) ?? null;
}

export function isCustom(override: DatesByType | null | undefined): boolean {
  return !!override && Object.keys(override).length > 0;
}

/** What a hire follows for any type they have no date of their own for:
 *  the crew's dates — and for talent, nothing. Talent keep their own
 *  schedule (backend job_dates.base_dates). */
export function baseDates(crewDates: DatesByType, kind?: string | null): DatesByType {
  return kind === "talent" ? {} : crewDates;
}

/** The talent table's date columns; a fitting (prep) or a down day goes in
 *  the "Other days" column. */
export const TALENT_TYPES: DayType[] = ["travel", "shoot", "travel_out"];
export const TALENT_OTHER_TYPES: DayType[] = ["prep", "off"];

/** A hire's actual dates: their own where they have them, the crew's
 *  everywhere else. The API already returns this per hire as
 *  `effective_dates`; this is only for a local edit preview. */
export function effectiveDates(crewDates: DatesByType, override: DatesByType): DatesByType {
  const out: DatesByType = {};
  for (const t of DAY_TYPES) out[t] = t in override ? override[t] : crewDates[t] ?? [];
  return out;
}

/** Every ISO date in a 6-week grid covering `month` ("2026-10"), starting on
 *  the Sunday on/before the 1st — what RangeCalendar renders. */
export function monthGrid(month: string): string[] {
  const first = toLocalDate(`${month}-01`);
  const start = addDays(toIso(first), -first.getDay());
  const days: string[] = [];
  for (let i = 0; i < 42; i++) days.push(addDays(start, i));
  return days;
}

/** Which day type (if any) a date falls inside, given a lookup of that
 *  person's own blocks per type. Used to tint the calendar. */
export function typeOn(get: (t: DayType) => Span[], day: string): DayType | null {
  for (const t of DAY_TYPES) {
    for (const [a, b] of get(t)) if (day >= a && day <= b) return t;
  }
  return null;
}

export function sameSpans(a: Span[], b: Span[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function sortSpans(spans: Span[]): Span[] {
  return [...spans].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}

/** The date the calendar should offer first for the crew's `type`, from what's
 *  already set and the job's own shoot days (`days`, ISO, any order). Travel
 *  lands the day before everything else, prep just before the shoot, the shoot
 *  on the first day the job already has, wrap the day after. Null when there's
 *  nothing to go on — the caller falls back to today.
 *
 *  Path of least resistance: a producer who made the job for Oct 5 should open
 *  the Travel in picker on Oct 4 with it highlighted, not on today's month. */
export function suggestFor(type: DayType, crewDates: DatesByType, days: string[]): string | null {
  const spans = DAY_TYPES.flatMap((t) => crewDates[t] ?? []);
  const earliest = spans.length ? spans.map((s) => s[0]).sort()[0] : null;
  const latestOf = (types: DayType[]) => {
    const ends = types.flatMap((t) => (crewDates[t] ?? []).map((s) => s[1])).sort();
    return ends.length ? ends[ends.length - 1] : null;
  };
  const dated = days.filter(Boolean).sort();
  const firstDay = dated[0] ?? null;
  const lastDay = dated[dated.length - 1] ?? null;
  const shootStart = (crewDates.shoot ?? []).map((s) => s[0]).sort()[0] ?? firstDay;

  switch (type) {
    case "travel": {
      const anchor = earliest && firstDay ? (earliest < firstDay ? earliest : firstDay) : earliest ?? firstDay;
      return anchor ? addDays(anchor, -1) : null;
    }
    case "prep": {
      const travelEnd = latestOf(["travel"]);
      if (travelEnd) return addDays(travelEnd, 1);
      return shootStart ? addDays(shootStart, -1) : null;
    }
    case "shoot": {
      if (firstDay) return firstDay;
      const before = latestOf(["travel", "prep"]);
      return before ? addDays(before, 1) : null;
    }
    case "wrap": {
      const after = latestOf(["shoot"]) ?? lastDay ?? latestOf(["travel", "prep"]);
      return after ? addDays(after, 1) : null;
    }
    case "checkin": {
      // Someone already in town checks in the day the crew arrives.
      const travel = (crewDates.travel ?? []).map((s) => s[0]).sort()[0];
      if (travel) return travel;
      return shootStart ? addDays(shootStart, -1) : null;
    }
    case "off": {
      // A down day falls between shoot days: the day after the first one.
      const firstShoot = (crewDates.shoot ?? []).map((s) => s[1]).sort()[0];
      return firstShoot ? addDays(firstShoot, 1) : shootStart ? addDays(shootStart, 1) : null;
    }
    case "travel_out": {
      // The day after the wrap if there is one, else after the shoot.
      const after = latestOf(["wrap"]) ?? latestOf(["shoot"]) ?? lastDay ?? latestOf(["travel", "prep"]);
      return after ? addDays(after, 1) : null;
    }
  }
}

/** Every date in a set of spans, in order, each once. */
export function datesIn(spans: Span[]): string[] {
  const out = new Set<string>();
  for (const [a, b] of spans) for (let d = a; d <= b; d = addDays(d, 1)) out.add(d);
  return [...out].sort();
}

/** One entry on the Shoot days tab: a real day, or a placeholder for a crew
 *  shoot date that has no day yet. */
export interface PlannedDay<D> {
  kind: "day" | "placeholder";
  date: string | null;
  day: D | null;
  /** "Day N": the shoot days, in date order — placeholders count, since
   *  they're days of the shoot that simply aren't set up yet. Null for a day
   *  off the shoot dates (a scout, a travel day) and for an undated one. */
  number: number | null;
  /** For an unnumbered dated day: which of the crew's other day types it
   *  falls on, if any. */
  dayType: DayType | null;
  /** A dated day on none of the crew's dates at all — worth a look, and
   *  worth offering to move. */
  outside: boolean;
  /** For an outside day: before the crew's first date, after their last, or
   *  in a gap between — what its label says (offDatesLabel). */
  where?: "before" | "after" | "between";
}

/** The job's days as the Shoot days tab lays them out, and what "Day N of M"
 *  means everywhere (the day sidebar reads this too). With no shoot dates
 *  set, the days just number in order — there's nothing to plan against. */
export function planDays<D extends { shoot_date: string | null }>(days: D[], crewDates: DatesByType): PlannedDay<D>[] {
  const shootDates = datesIn(crewDates.shoot ?? []);
  if (!shootDates.length) {
    return days.map((d, i) => ({ kind: "day", date: d.shoot_date, day: d, number: i + 1, dayType: null, outside: false }));
  }
  const get = (t: DayType) => crewDates[t] ?? [];
  const entries: PlannedDay<D>[] = [];
  for (const date of shootDates) {
    const onIt = days.filter((d) => d.shoot_date === date);
    if (!onIt.length) entries.push({ kind: "placeholder", date, day: null, number: null, dayType: "shoot", outside: false });
    for (const d of onIt) entries.push({ kind: "day", date, day: d, number: null, dayType: "shoot", outside: false });
  }
  const every = datesIn(DAY_TYPES.flatMap((t) => get(t)));
  for (const d of days) {
    if (d.shoot_date && shootDates.includes(d.shoot_date)) continue;
    const t = d.shoot_date ? typeOn(get, d.shoot_date) : null;
    const outside = !!d.shoot_date && !t;
    const where = !outside ? undefined
      : d.shoot_date! < every[0] ? "before" as const
        : d.shoot_date! > every[every.length - 1] ? "after" as const : "between" as const;
    entries.push({ kind: "day", date: d.shoot_date, day: d, number: null, dayType: t, outside, where });
  }
  // Dated in date order, undated last; stable, so two days on one date keep
  // the API's order.
  entries.sort((a, b) => (a.date === null ? 1 : 0) - (b.date === null ? 1 : 0) || (a.date ?? "").localeCompare(b.date ?? ""));
  let n = 0;
  for (const e of entries) if (e.dayType === "shoot") e.number = ++n;
  return entries;
}

/** What a day on none of the crew's dates is called — on its Shoot days card
 *  and in its own sidebar. Said by where it sits, which is what a producer
 *  needs to know: "Before the job's dates" / "After the job's dates", or an
 *  "Extra day" in a gap between them. Not "Wrapped" for a past day, which
 *  reads as a wrap day, and not "Off the shoot dates", which read oddly
 *  (Patrick, 2026-09-28). */
export function offDatesLabel(where: "before" | "after" | "between" | undefined): string {
  return where === "before" ? "Before the job's dates" : where === "after" ? "After the job's dates" : "Extra day";
}
