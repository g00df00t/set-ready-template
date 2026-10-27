/* The job-dates formatter, checked against the same lines the backend checks.
 *
 *   cd frontend && node --experimental-strip-types tests/job-dates.test.ts
 *
 * ../backend/tests/date_line_cases.json is shared with
 * backend/tests/test_crew_date_conflicts.py — one file of cases, read by both
 * sides, so the deal memo's Dates block (rendered server side) and the Crew &
 * dates table (rendered here) can't quietly drift into disagreeing about what
 * "Oct 13th (Tue) – Oct 15th (Thu) - Shoot day" means.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  DAY_TYPES, addDays, baseDates, datesBlock, datesIn, offDatesLabel, planDays, displaySpan, effectiveDates, formatLine,
  formatSpan, isCustom, monthGrid, nextCrewType, noneLabel, sameSpans, spanDays, suggestFor, typeOn,
  type DatesByType, type DayType,
} from "../src/lib/jobDates.ts";

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  — " + detail}`);
  if (!ok) FAILS.push(name);
}

const casesPath = fileURLToPath(new URL("../../backend/tests/date_line_cases.json", import.meta.url));
const { cases } = JSON.parse(readFileSync(casesPath, "utf8")) as {
  cases: { type: DayType; span: [string, string]; line: string }[];
};

console.log("\nShared date-line cases — must match the backend exactly");
for (const c of cases) {
  const got = formatLine(c.type, c.span[0], c.span[1]);
  check(JSON.stringify(c.line), got === c.line, `got ${JSON.stringify(got)}`);
}

const CREW: DatesByType = {
  travel: [["2026-10-11", "2026-10-11"]],
  prep: [["2026-10-12", "2026-10-12"]],
  shoot: [["2026-10-13", "2026-10-15"]],
  wrap: [],
  travel_out: [["2026-10-16", "2026-10-16"]],
};

console.log("\nEffective dates");
check("no override follows the crew exactly",
  JSON.stringify(effectiveDates(CREW, {})) === JSON.stringify(Object.fromEntries(DAY_TYPES.map((t) => [t, CREW[t] ?? []]))));
check("an empty list is 'none'", (effectiveDates(CREW, { travel: [] }).travel ?? []).length === 0);
check("everything else still follows the crew",
  sameSpans(effectiveDates(CREW, { travel: [] }).shoot ?? [], CREW.shoot!));

console.log("\nTalent keep their own schedule (backend base_dates)");
const WITH_PREP: DatesByType = { ...CREW, prep: [["2026-10-12", "2026-10-12"]] };
check("crew follow every crew date", baseDates(WITH_PREP, "crew") === WITH_PREP);
check("no kind reads as crew", baseDates(WITH_PREP, undefined) === WITH_PREP);
check("talent follow nothing", Object.keys(baseDates(WITH_PREP, "talent")).length === 0);
check("a talent with no dates has none",
  DAY_TYPES.every((t) => (effectiveDates(baseDates(WITH_PREP, "talent"), {})[t] ?? []).length === 0));
check("...and a fitting set on their hire is theirs",
  (effectiveDates(baseDates(WITH_PREP, "talent"), { prep: [["2026-10-12", "2026-10-12"]] }).prep ?? []).length === 1);

console.log("\nisCustom");
check("no keys at all is not custom", !isCustom({}));
check("an explicit empty list IS custom — that's how 'None' is recorded", isCustom({ travel: [] }));

console.log("\nOn-screen span format (the mockup's, not the deal memo's)");
check("one day", displaySpan("2026-10-04", "2026-10-04") === "Sun, Oct 4", displaySpan("2026-10-04", "2026-10-04"));
check("within a month, the end is just the day", displaySpan("2026-10-07", "2026-10-10") === "Oct 7 → 10");
check("across months, both ends are named", displaySpan("2026-10-30", "2026-11-02") === "Oct 30 → Nov 2");

console.log("\nWhere the crew calendar opens (the job was made for Oct 5)");
const DAYS = ["2026-10-05"];
check("Travel in suggests the day before the job's first day", suggestFor("travel", {}, DAYS) === "2026-10-04");
check("Shoot suggests the job's first day", suggestFor("shoot", {}, DAYS) === "2026-10-05");
check("Prep follows a travel day already set",
  suggestFor("prep", { travel: [["2026-10-04", "2026-10-04"]] }, DAYS) === "2026-10-05");
check("Wrap follows the shoot",
  suggestFor("wrap", { shoot: [["2026-10-06", "2026-10-09"]] }, DAYS) === "2026-10-10");
check("Wrap with no shoot set follows the job's last day", suggestFor("wrap", {}, ["2026-10-05", "2026-10-07"]) === "2026-10-08");
check("Travel goes before anything already set, even before the first day",
  suggestFor("travel", { prep: [["2026-10-02", "2026-10-03"]] }, DAYS) === "2026-10-01");
check("nothing to go on is null (the caller uses today)", suggestFor("travel", {}, []) === null);

console.log("\nSetup walks the crew's dates: shoot, then travel out, travel in, prep, wrap day");
const SHOOT: DatesByType = { shoot: [["2026-10-05", "2026-10-07"]] };
check("nothing set asks for the shoot", nextCrewType({}) === "shoot");
check("an empty shoot still asks for the shoot — it can't be 'none'", nextCrewType({ shoot: [] }) === "shoot");
check("after the shoot comes travel out", nextCrewType(SHOOT) === "travel_out");
check("'none' answers a type (an empty list)", nextCrewType({ ...SHOOT, travel_out: [] }) === "travel");
check("then prep", nextCrewType({ ...SHOOT, travel_out: [], travel: [["2026-10-04", "2026-10-04"]] }) === "prep");
check("the wrap day comes last — usually only the stylists'",
  nextCrewType({ ...SHOOT, travel_out: [], travel: [], prep: [] }) === "wrap");
check("all answered is null", nextCrewType({ ...SHOOT, travel_out: [], travel: [], prep: [], wrap: [] }) === null);
const nones = [noneLabel("travel"), noneLabel("prep"), noneLabel("wrap"), noneLabel("travel_out")].join("|");
check("button labels read naturally", nones === "No travel in|No prep|No wrap day|No travel out", nones);
check("travel out follows a wrap day",
  suggestFor("travel_out", { shoot: [["2026-10-13", "2026-10-15"]], wrap: [["2026-10-16", "2026-10-16"]] }, []) === "2026-10-17");
check("...or the shoot, when there's no wrap day",
  suggestFor("travel_out", { shoot: [["2026-10-13", "2026-10-15"]] }, []) === "2026-10-16");

console.log("\nPlanning the Shoot days tab");
check("datesIn expands spans, once each", datesIn([["2026-10-13", "2026-10-15"], ["2026-10-14", "2026-10-16"]]).join() ===
  "2026-10-13,2026-10-14,2026-10-15,2026-10-16");
const PLAN_DATES: DatesByType = { prep: [["2026-10-12", "2026-10-12"]], shoot: [["2026-10-13", "2026-10-16"]] };
const plan = planDays([
  { id: "a", shoot_date: "2026-10-13" },
  { id: "old", shoot_date: "2026-08-24" },
  { id: "scout", shoot_date: "2026-10-12" },
  { id: "u", shoot_date: null },
], PLAN_DATES);
const label = (e: (typeof plan)[number]) => `${e.kind}:${e.date}:${e.number}:${e.dayType}:${e.outside}`;
check("a real day on a shoot date is numbered; missing shoot dates become placeholders, numbered too",
  plan.filter((e) => e.number).map((e) => `${e.kind}:${e.number}`).join() === "day:1,placeholder:2,placeholder:3,placeholder:4",
  plan.map(label).join(" | "));
check("a day on a prep date isn't numbered, and says it's prep", plan.some((e) => e.day?.id === "scout" && e.number === null && e.dayType === "prep" && !e.outside));
check("a day on none of the crew's dates is flagged outside", plan.some((e) => e.day?.id === "old" && e.outside && e.number === null));
check("everything's in date order, the undated day last", plan.map((e) => e.date ?? "none").join() ===
  "2026-08-24,2026-10-12,2026-10-13,2026-10-14,2026-10-15,2026-10-16,none", plan.map(label).join(" | "));
check("no shoot dates: the days just number in order",
  planDays([{ shoot_date: "2026-08-24" }, { shoot_date: null }], {}).map((e) => e.number).join() === "1,2");

check("a day before the crew's first date says so", offDatesLabel("before") === "Before the job's dates");
check("...after their last", offDatesLabel("after") === "After the job's dates");
check("...in a gap between is an 'Extra day'", offDatesLabel("between") === "Extra day");
const gap = planDays([{ shoot_date: "2026-08-24" }, { shoot_date: "2026-10-20" }, { shoot_date: "2026-10-14" }],
  { shoot: [["2026-10-13", "2026-10-13"], ["2026-10-15", "2026-10-16"]], travel_out: [["2026-10-17", "2026-10-17"]] });
const where = gap.filter((e) => e.outside).map((e) => `${e.date}:${e.where}`).join();
check("planDays says where each outside day sits",
  where === "2026-08-24:before,2026-10-14:between,2026-10-20:after", where);

console.log("\nSpan length");
check("a single day is 1", spanDays("2026-10-13", "2026-10-13") === 1);
check("a three-day span is 3", spanDays("2026-10-13", "2026-10-15") === 3);

console.log("\naddDays / month grid");
check("addDays crosses a month boundary", addDays("2026-10-31", 1) === "2026-11-01");
const grid = monthGrid("2026-10");
check("a month grid is always 42 days", grid.length === 42);
check("it starts on a Sunday", toWeekday(grid[0]) === 0);
check("it contains every day of October 2026", grid.filter((d) => d.startsWith("2026-10")).length === 31);

console.log("\ntypeOn");
const get = (t: DayType) => CREW[t] ?? [];
check("a date inside the shoot span reads as 'shoot'", typeOn(get, "2026-10-14") === "shoot");
check("a date outside every span reads as null", typeOn(get, "2026-10-20") === null);

console.log("\ndatesBlock — the live preview, in job order");
const block = datesBlock(CREW, {
  travel: [],
  shoot: [["2026-10-13", "2026-10-13"], ["2026-10-15", "2026-10-15"]],
});
check("matches the backend's own case exactly", block === [
  "Oct 12th - Mon - Prep/Scout",
  "Oct 13th - Tue - Shoot day",
  "Oct 15th - Thu - Shoot day",
  "Oct 16th - Fri - Travel out",
].join("\n"), block);

check("every DAY_TYPES entry has a label", DAY_TYPES.every((t) => typeof t === "string"));

function toWeekday(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).getDay();
}

console.log();
console.log(FAILS.length ? `${FAILS.length} FAILED: ${FAILS.join(", ")}` : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
