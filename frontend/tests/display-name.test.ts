/* The display-name rule, frontend copy.
 *
 *   cd frontend && node --experimental-strip-types tests/display-name.test.ts
 *
 * These are the SAME cases as backend/tests/test_display_name.py, on purpose.
 * The two implementations exist so the account page can preview what crew will
 * receive; if they drift, the preview starts lying. Run both after touching
 * either.
 *
 * Hostile inputs are built with fromCharCode so this file stays free of the
 * control characters it is about.
 */

import { cleanDisplayName, fromLine, NAME_MAX } from "../src/lib/displayName.ts";

const LF = String.fromCharCode(10);
const CR = String.fromCharCode(13);
const TAB = String.fromCharCode(9);
const NUL = String.fromCharCode(0);
const ESC = String.fromCharCode(27);

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -- " + detail}`);
  if (!ok) FAILS.push(name);
}
function eq(label: string, raw: string | null | undefined, expected: string | null) {
  const got = cleanDisplayName(raw);
  check(label, got === expected, `${JSON.stringify(raw)} -> ${JSON.stringify(got)}, wanted ${JSON.stringify(expected)}`);
}

console.log("\nOrdinary names survive untouched");
eq("a plain name", "Pat Kehoe", "Pat Kehoe");
eq("a company name", "Kehoe Productions", "Kehoe Productions");
eq("an apostrophe", "Siobhan O'Connor", "Siobhan O'Connor");
eq("accents and a hyphen", "Jean-Luc Beart", "Jean-Luc Beart");
eq("an ampersand", "Smith & Co.", "Smith & Co.");

console.log("\nHeader injection is the reason this function exists");
eq("a newline becomes a space", "Pat" + LF + "Bcc: victim@example.com", "Pat Bcc: victim@example.com");
eq("CRLF likewise", "Pat" + CR + LF + "Bcc: victim@example.com", "Pat Bcc: victim@example.com");
check("no output can ever contain CR or LF",
  ["a" + LF + "b", "a" + CR + LF + "b", LF, CR, "a" + LF + LF + LF + "b"]
    .map((v) => cleanDisplayName(v) ?? "")
    .every((r) => !r.includes(CR) && !r.includes(LF)));
eq("a NUL byte", "Pat" + NUL + "Kehoe", "PatKehoe");
eq("an ANSI escape", "Pat" + ESC + "[31mKehoe", "Pat[31mKehoe");

console.log("\nWhitespace is tidied, not merely stripped");
eq("leading and trailing space", "  Pat Kehoe  ", "Pat Kehoe");
eq("a tab between words becomes one space", "Pat" + TAB + "Kehoe", "Pat Kehoe");
eq("a run of spaces collapses", "Pat    Kehoe", "Pat Kehoe");
eq("newlines between words leave a single space", "Pat " + LF + LF + " Kehoe", "Pat Kehoe");

console.log("\nNothing is nothing -- the caller falls back to plain 'Set Ready'");
eq("null", null, null);
eq("undefined", undefined, null);
eq("empty string", "", null);
eq("only spaces", "     ", null);
eq("only control characters", LF + CR + TAB, null);
// @ts-expect-error deliberately passing a non-string, as malformed metadata would
eq("a non-string", 12345, null);

console.log("\nLength is bounded");
const out = cleanDisplayName("Wolfeschlegelsteinhausenbergerdorff ".repeat(6));
check(`capped at ${NAME_MAX} characters`, out !== null && out.length <= NAME_MAX, `got ${out?.length}`);
check("a capped name has no trailing space", out === out?.trim());
eq("a name exactly at the cap is untouched", "A".repeat(NAME_MAX), "A".repeat(NAME_MAX));

console.log("\nWhat crew actually see on the From line");
check("a name reads as theirs", fromLine("Pat Kehoe") === "Pat Kehoe via Set Ready");
check("no name falls back", fromLine(null) === "Set Ready");
check("whitespace-only falls back", fromLine("   ") === "Set Ready");

console.log();
console.log(FAILS.length ? `${FAILS.length} FAILURES: ${FAILS.join(", ")}` : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
