/* Typing money in and showing it out, for the budget and PC log screens.
 * Must agree with backend services/pc_log.py's dollars().
 *
 *   cd frontend && node --experimental-strip-types tests/money.test.ts
 */

import { bpToPct, centsToInput, formatCents, parseBp, parseCents } from "../src/lib/money.ts";

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  — " + detail}`);
  if (!ok) FAILS.push(name);
}

check("two places, commas", formatCents(130050) === "$1,300.50", formatCents(130050));
check("whole dollars still show .00", formatCents(500000) === "$5,000.00");
check("pennies", formatCents(7) === "$0.07");
check("negative", formatCents(-11358) === "-$113.58", formatCents(-11358));
check("nothing for unset", formatCents(null) === "" && formatCents(undefined) === "");
check("an input gets the plain figure", centsToInput(130050) === "1300.50" && centsToInput(null) === "");
check("typed with commas and a sign", parseCents("$1,300.5") === 130050);
check("exact where floats aren't: 0.29", parseCents("0.29") === 29 && parseCents("1291.87") === 129187);
check("whole dollars", parseCents("842") === 84200);
check("blank is null", parseCents("  ") === null);
check("three decimals isn't an amount", parseCents("1.234") === undefined);
check("letters aren't", parseCents("12a") === undefined && parseCents("-5") === undefined);
check("over $10M isn't", parseCents("10000000.01") === undefined);
check("percent to basis points", parseBp("8") === 800 && parseBp("7.5") === 750 && parseBp("8%") === 800);
check("over 100% isn't", parseBp("101") === undefined && parseBp("x") === undefined);
check("basis points to percent", bpToPct(800) === "8" && bpToPct(750) === "7.5");

console.log(FAILS.length ? `${FAILS.length} FAILED` : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
