/* Which project a returning producer should land on.
 *
 * Pulled out of the welcome page so it can be tested without a browser, a
 * session, or a database — the date handling here has two traps that are
 * invisible until someone is in the wrong timezone or standing on set.
 */

export interface ShootProject {
  id: string;
  name: string;
  shoot_date: string | null;
  created_at: string;
}

/** Today at local midnight. A shoot happening TODAY is still ahead of you —
 *  comparing against `new Date()` would drop the current job at 00:01. */
export function today(now: Date = new Date()): Date {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** "2026-09-14" → local midnight, not UTC midnight.
 *  Without the time part the browser parses a date-only string as UTC, so
 *  anywhere west of Greenwich the shoot renders as the day before. */
export function asDate(shootDate: string): Date {
  return new Date(shootDate + "T00:00:00");
}

/** The soonest shoot still ahead, else the newest project.
 *
 * The fallback matters: a producer between jobs, or one who hasn't set a date
 * yet, should still land on something rather than an empty page. */
export function pickNext(projects: ShootProject[], now: Date = new Date()): ShootProject | null {
  if (projects.length === 0) return null;
  const floor = today(now);
  const upcoming = projects
    .filter((p) => p.shoot_date && asDate(p.shoot_date) >= floor)
    .sort((a, b) => asDate(a.shoot_date!).getTime() - asDate(b.shoot_date!).getTime());
  if (upcoming.length > 0) return upcoming[0];
  return [...projects].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )[0];
}

/** True when this project is genuinely upcoming, so the card can label itself
 *  "Next shoot" rather than "Most recent". */
export function isUpcoming(p: ShootProject, now: Date = new Date()): boolean {
  return !!p.shoot_date && asDate(p.shoot_date) >= today(now);
}

/** True when the shoot is TODAY — not merely still ahead.
 *
 * Narrower than isUpcoming, and the welcome greeting leads with it, so the
 * date discipline in this file is doing real work: asDate gives local midnight
 * rather than UTC, which is what stops a producer west of Greenwich being told
 * "Shoot day" the evening before it. */
export function isToday(p: { shoot_date: string | null }, now: Date = new Date()): boolean {
  return !!p.shoot_date && asDate(p.shoot_date).getTime() === today(now).getTime();
}

/** True when the shoot day is behind us, so the job can be treated as finished.
 *
 * The mirror of isUpcoming, and deliberately not `!isUpcoming` — a project with
 * no date is neither upcoming nor wrapped, and calling it wrapped would offer a
 * wrap report for a day that hasn't been planned.
 *
 * Matches the backend's is_wrapped() in services/wrap_report_data.py: strictly
 * before today, so the report doesn't appear while the crew is still on set. */
export function hasWrapped(p: { shoot_date: string | null }, now: Date = new Date()): boolean {
  return !!p.shoot_date && asDate(p.shoot_date) < today(now);
}
