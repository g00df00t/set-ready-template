// A hire's agreed rates, as the Pre-production screen shows them. The rules —
// what gets suggested, what prints on the memo — live in the backend's
// services/job_rates.py; this file only formats.

export interface Rates {
  rate_shoot: number | null;
  rate_travel: number | null;
  rate_prep: number | null;
  rate_note: string | null;
}

export interface RateSuggestion extends Rates {
  rate_source: "job" | "roster";
  rate_source_job_id: string | null;
  rate_source_job_name?: string | null;
}

export type PrepMode = "full" | "half" | "custom";

// PostgREST can hand numeric back as a string; the screen only wants numbers.
export function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

// "$1,200", cents only when there are any — the backend's money().
export function money(v: unknown): string {
  const n = num(v);
  if (n === null) return "";
  return n % 1 ? `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : `$${n.toLocaleString("en-US")}`;
}

export function hasRates(r: Partial<Rates>): boolean {
  return num(r.rate_shoot) !== null || num(r.rate_travel) !== null || num(r.rate_prep) !== null;
}

// ["$800 shoot", "$400 travel", "$400 prep"] — only the ones that are set.
// One per line in the table, which keeps the Rate column narrow.
export function rateLines(r: Partial<Rates>): string[] {
  return ([["rate_shoot", "shoot"], ["rate_travel", "travel"], ["rate_prep", "prep"]] as const)
    .filter(([f]) => num(r[f]) !== null)
    .map(([f, label]) => `${money(r[f])} ${label}`);
}

// "$800 shoot · $400 travel · $400 prep", for a single line.
export function rateSummary(r: Partial<Rates>): string {
  return rateLines(r).join(" · ");
}

// Which of Full / ½ / Custom a prep rate is, against the shoot rate.
export function prepModeOf(shoot: number | null, prep: number | null): PrepMode {
  if (shoot === null || prep === null) return prep === null ? "full" : "custom";
  if (prep === shoot) return "full";
  if (prep === Math.round(shoot * 50) / 100) return "half";
  return "custom";
}

export function prepFor(mode: PrepMode, shoot: number | null, custom: number | null): number | null {
  if (mode === "custom") return custom;
  if (shoot === null) return null;
  return mode === "full" ? shoot : Math.round(shoot * 50) / 100;
}

// What a typed amount is, keeping only digits and one point.
export function cleanAmount(text: string): string {
  const kept = text.replace(/[^\d.]/g, "");
  const [whole, ...rest] = kept.split(".");
  return rest.length ? `${whole}.${rest.join("").slice(0, 2)}` : whole;
}
