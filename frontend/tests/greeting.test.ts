/* What the welcome page says, and at what hour it says it.
 *
 *   cd frontend && node --experimental-strip-types tests/greeting.test.ts
 *
 * Tests the real module, not a copy of it — Node 22.6+ strips the types.
 * `now` is injected everywhere, so these don't depend on when they're run.
 */

import { greeting, daypart } from "../src/lib/greeting.ts";

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  — " + detail}`);
  if (!ok) FAILS.push(name);
}

/** Local time, deliberately — no Z. The greeting reads the viewer's own clock,
 *  so a UTC literal here would be testing the wrong hour. */
const at = (hhmm: string) => new Date(`2026-09-14T${hhmm}:00`);

console.log("\nEach hour lands in the right daypart");
check("00:30 → night",      daypart(at("00:30")) === "night");
check("04:00 → early",      daypart(at("04:00")) === "early", "4am is the start of a call, not the middle of the night");
check("05:45 → early",      daypart(at("05:45")) === "early");
check("06:00 → morning",    daypart(at("06:00")) === "morning");
check("11:59 → morning",    daypart(at("11:59")) === "morning");
check("12:00 → afternoon",  daypart(at("12:00")) === "afternoon", "noon is afternoon, not morning");
check("16:59 → afternoon",  daypart(at("16:59")) === "afternoon");
check("17:00 → evening",    daypart(at("17:00")) === "evening");
check("21:59 → evening",    daypart(at("21:59")) === "evening");
check("22:00 → night",      daypart(at("22:00")) === "night");

console.log("\nReads as a sentence with a name and without one");
check("with a name",    greeting({ name: "Pat", now: at("14:00") }) === "Good afternoon, Pat.");
check("without a name", greeting({ name: null,  now: at("14:00") }) === "Good afternoon.",
  "firstName returns null rather than greeting someone as their email local-part");
check("empty string counts as no name",
  greeting({ name: "", now: at("14:00") }) === "Good afternoon.");
check("no options at all still returns a sentence",
  /^[A-Z].*\.$/.test(greeting()));

console.log("\nShoot day outranks the clock");
check("shoot day in the afternoon",
  greeting({ name: "Pat", shootToday: true, now: at("14:00") }) === "Shoot day, Pat.");
check("shoot day at a 5am call",
  greeting({ name: "Pat", shootToday: true, now: at("05:00") }) === "Shoot day, Pat.",
  "the day is more worth saying than the hour");
check("shoot day without a name",
  greeting({ shootToday: true, now: at("14:00") }) === "Shoot day.");
check("no shoot today → back to the clock",
  greeting({ name: "Pat", shootToday: false, now: at("05:00") }) === "Early start, Pat.");

console.log("\nThe unusual hours producers actually keep");
check("4:40am is an early start, not a good morning",
  greeting({ name: "Pat", now: at("04:40") }) === "Early start, Pat.");
check("11pm is working late",
  greeting({ name: "Pat", now: at("23:00") }) === "Working late, Pat.");

console.log();
console.log(FAILS.length ? `${FAILS.length} FAILURES: ${FAILS.join(", ")}` : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
