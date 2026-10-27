/* What the welcome page says when a producer comes back.
 *
 * Kept out of the page so the wording and the hour boundaries can be tested
 * without a browser or a session — the same reason nextShoot.ts exists.
 *
 * ⚠️ This must only ever run in the browser. The hour it reads is the *viewer's*
 * local hour, which is the whole reason no timezone has to be stored or asked
 * for: their clock already knows. Render it on the server instead and you get
 * Vercel's UTC hour, which disagrees with the browser and makes React swap the
 * text after paint. welcome/page.tsx holds this behind its `ready` flag, so the
 * greeting appears once, correct, along with the rest of the page.
 */

export type Daypart = "early" | "morning" | "afternoon" | "evening" | "night";

/** Local hour → daypart.
 *
 * The bands are set for people who shoot. `early` exists because a 5am call is
 * ordinary here and "Good morning" at 4:40 reads as if the app hasn't noticed
 * what kind of day this is. It stays narrow — two hours — because the charm of
 * an unusual greeting wears off fast, and the other four are deliberately plain
 * for the same reason.
 */
export function daypart(now: Date = new Date()): Daypart {
  const h = now.getHours();
  if (h >= 22 || h < 4) return "night";
  if (h < 6) return "early";
  if (h < 12) return "morning";
  if (h < 17) return "afternoon";
  return "evening";
}

const LEAD: Record<Daypart, string> = {
  night: "Working late",
  early: "Early start",
  morning: "Good morning",
  afternoon: "Good afternoon",
  evening: "Good evening",
};

export interface GreetingOptions {
  /** First name, or null when we don't have one worth using. `firstName` in the
   *  welcome page returns null rather than greeting someone as "p.kehoe", so
   *  every lead here has to read as a whole sentence on its own. */
  name?: string | null;
  /** True when the shoot is TODAY. Takes precedence over the clock: the day
   *  itself is the more useful thing to say, and it's the one thing this app
   *  knows that a generic greeting can't. */
  shootToday?: boolean;
  now?: Date;
}

export function greeting({ name, shootToday = false, now = new Date() }: GreetingOptions = {}): string {
  const lead = shootToday ? "Shoot day" : LEAD[daypart(now)];
  return name ? `${lead}, ${name}.` : `${lead}.`;
}
