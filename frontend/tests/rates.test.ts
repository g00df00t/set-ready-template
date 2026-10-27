/* A hire's rates on screen: money, the summary, and the Full / ½ / Custom
 * prep switch. Must agree with backend services/job_rates.py's money().
 *
 *   cd frontend && node --experimental-strip-types tests/rates.test.ts
 */

import { cleanAmount, hasRates, money, prepFor, prepModeOf, rateSummary } from "../src/lib/rates.ts";

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  — " + detail}`);
  if (!ok) FAILS.push(name);
}

check("money: commas, no .00", money(1200) === "$1,200", money(1200));
check("money: cents when there are some", money("62.5") === "$62.50", money("62.5"));
check("money: nothing for unset", money(null) === "");
check("summary: only what's set, in order",
  rateSummary({ rate_shoot: 800, rate_travel: null, rate_prep: 400 }) === "$800 shoot · $400 prep");
check("hasRates: a string amount from PostgREST counts", hasRates({ rate_shoot: "800" as unknown as number }));
check("hasRates: none set", !hasRates({ rate_shoot: null, rate_travel: null, rate_prep: null }));
check("prep equal to shoot is Full", prepModeOf(800, 800) === "full");
check("prep half of shoot is ½", prepModeOf(850, 425) === "half");
check("anything else is Custom", prepModeOf(800, 500) === "custom");
check("½ of an odd rate keeps cents", prepFor("half", 825, null) === 412.5);
check("Custom keeps what was typed", prepFor("custom", 800, 300) === 300);
check("typing keeps digits and one point, two decimals", cleanAmount("$1,2a00.555") === "1200.55", cleanAmount("$1,2a00.555"));

console.log(FAILS.length ? `${FAILS.length} FAILED` : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
