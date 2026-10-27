/* Which shoot a returning producer lands on.
 *
 *   cd frontend && node --experimental-strip-types tests/next-shoot.test.ts
 *
 * Tests the real module, not a copy of it — Node 22.6+ strips the types.
 * `now` is injected so "today" is a fixed date and these don't start failing
 * tomorrow.
 */

import { pickNext, isUpcoming, isToday, hasWrapped, asDate, type ShootProject } from "../src/lib/nextShoot.ts";

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  — " + detail}`);
  if (!ok) FAILS.push(name);
}

const NOW = new Date("2026-09-14T15:30:00");   // mid-afternoon, on a shoot day
const p = (id: string, shoot_date: string | null, created_at = "2026-01-01T00:00:00Z"): ShootProject =>
  ({ id, name: id, shoot_date, created_at });

console.log("\nPicks the soonest shoot that is still ahead");
check("nearest future shoot wins",
  pickNext([p("nov", "2026-11-02"), p("sep", "2026-09-20"), p("oct", "2026-10-01")], NOW)?.id === "sep");
check("past shoots are not offered",
  pickNext([p("past", "2026-08-01"), p("future", "2026-09-20")], NOW)?.id === "future");

console.log("\nA shoot happening TODAY is still ahead of you");
check("today counts as upcoming, at 3:30pm on the day",
  pickNext([p("today", "2026-09-14"), p("tomorrow", "2026-09-15")], NOW)?.id === "today",
  "comparing against the clock instead of local midnight drops the current job");
check("isUpcoming agrees", isUpcoming(p("today", "2026-09-14"), NOW));
check("yesterday does not", !isUpcoming(p("yst", "2026-09-13"), NOW));

console.log("\nisToday is narrower than isUpcoming — the greeting leads with it");
check("the shoot dated today, at 3:30pm", isToday(p("today", "2026-09-14"), NOW));
check("a shoot next week is upcoming but NOT today",
  isUpcoming(p("later", "2026-09-20"), NOW) && !isToday(p("later", "2026-09-20"), NOW),
  "leading with \"Shoot day\" for any future shoot would say it every day");
check("yesterday is not today", !isToday(p("yst", "2026-09-13"), NOW));
check("no date is not today", !isToday(p("none", null), NOW));
check("the evening BEFORE, west of Greenwich, is still not shoot day",
  !isToday(p("tmw", "2026-09-15"), new Date("2026-09-14T23:30:00")),
  "a UTC parse here would roll over and greet them a day early");

console.log("\nFalls back rather than showing an empty page");
check("all shoots past → newest project by created_at",
  pickNext([p("old", "2026-01-05", "2026-01-05T00:00:00Z"),
            p("newer", "2026-02-05", "2026-06-05T00:00:00Z")], NOW)?.id === "newer");
check("no dates anywhere → newest project",
  pickNext([p("a", null, "2026-01-05T00:00:00Z"), p("b", null, "2026-08-05T00:00:00Z")], NOW)?.id === "b");
check("a dated future shoot beats a newer undated project",
  pickNext([p("undated", null, "2026-09-01T00:00:00Z"), p("dated", "2026-09-20", "2026-01-01T00:00:00Z")], NOW)?.id === "dated");
check("no projects at all → null", pickNext([], NOW) === null);
check("a single past project is still returned", pickNext([p("only", "2020-01-01")], NOW)?.id === "only");

console.log("\nWrapped is the mirror of upcoming, and neither claims an undated job");
check("yesterday's shoot has wrapped", hasWrapped(p("x", "2026-09-13"), NOW));
check("today's shoot has NOT wrapped — the crew is still on set",
  !hasWrapped(p("x", "2026-09-14"), NOW),
  "mid-afternoon on the day is not the same as the day being over");
check("a future shoot has not wrapped", !hasWrapped(p("x", "2026-09-20"), NOW));
check("an undated project is neither upcoming nor wrapped",
  !hasWrapped(p("x", null), NOW) && !isUpcoming(p("x", null), NOW),
  "calling it wrapped would offer a report for a day nobody has planned");

console.log("\nDate-only strings stay in local time");
const d = asDate("2026-09-14");
check("parses as local midnight, not UTC",
  d.getFullYear() === 2026 && d.getMonth() === 8 && d.getDate() === 14,
  `got ${d.toString()} — west of GMT a bare "2026-09-14" renders as the 13th`);

console.log();
console.log(FAILS.length ? `${FAILS.length} FAILURES: ${FAILS.join(", ")}` : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
