/* The import preview must not discard what the API tells it.
 *
 *   cd frontend && node --experimental-strip-types tests/import-preview-shape.test.ts
 *
 * handleParse rebuilds each row with an EXPLICIT shape rather than spreading the
 * response. That is deliberate — UI-only flags like deptCustom have no business
 * in the request body — but it silently drops anything the API starts sending.
 *
 * Which is exactly what happened: the duplicate verdict was computed on the
 * server, returned, and thrown away in this mapping. Every row read as "New",
 * nothing was ever flagged, and it looked like a deploy problem for two rounds
 * of testing.
 *
 * So this asserts the mapping and the request body both carry every
 * API-populated field. It reads source rather than running React, which is
 * cruder than a component test but catches the specific mistake that was made.
 */

import { readFileSync } from "node:fs";

const SRC = "src/app/projects/[id]/crew/page.tsx";
const src = readFileSync(SRC, "utf8");

/** Fields set by /crew/import/parse — see backend/models/crew.py. */
const FROM_API = ["match_state", "match_id", "match_name", "differs", "action"];

const FAILS: string[] = [];
function check(name: string, ok: boolean, detail = "") {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -- " + detail}`);
  if (!ok) FAILS.push(name);
}

function block(startMarker: string, endMarker: string): string {
  const i = src.indexOf(startMarker);
  if (i === -1) throw new Error(`could not find ${startMarker} in ${SRC}`);
  const j = src.indexOf(endMarker, i);
  return src.slice(i, j === -1 ? undefined : j);
}

console.log("\nThe parse response survives into the preview rows");
const parseMapping = block("setImportPreview(result.members.map(", "setImportPhase(\"preview\")");
for (const field of FROM_API) {
  check(`handleParse carries ${field}`, parseMapping.includes(field),
    "dropped here means the verdict is computed and then discarded");
}

console.log("\nThe producer's choice survives back to the API");
const confirmBody = block("const valid = importPreview", "if (!valid.length)");
for (const field of ["match_state", "match_id", "action"]) {
  check(`handleImportConfirm sends ${field}`, confirmBody.includes(field),
    "without this the API cannot link, and an override is ignored");
}

console.log("\nThe interface still declares them");
// Not block(): the interface contains nested braces (the `differs` type), so a
// first-"}" scan stops early and reports fields declared after it as missing.
const iface = block("interface ImportPreviewMember {", "\ninterface ");
for (const field of FROM_API) {
  check(`ImportPreviewMember declares ${field}`, iface.includes(field));
}

/* The Roster page has the same explicit mapping, and the same way to go wrong.
 * Both its imports — a paste and a call sheet upload — say whether each person
 * is already on the Roster, and the upload types every person; dropping `type`
 * would file a sheet's talent and clients as crew without a word. One function,
 * toPreviewRows, maps both, so both handlers must go through it. */
const ROSTER_SRC = "src/app/roster/page.tsx";
const roster = readFileSync(ROSTER_SRC, "utf8");
function rosterBlock(startMarker: string, endMarker: string): string {
  const i = roster.indexOf(startMarker);
  if (i === -1) throw new Error(`could not find ${startMarker} in ${ROSTER_SRC}`);
  const j = roster.indexOf(endMarker, i);
  return roster.slice(i, j === -1 ? undefined : j);
}

console.log("\nRoster: the import response survives into the preview rows");
const rosterMapping = rosterBlock("function toPreviewRows(", "\n}\n");
for (const [api, row] of [["type", "type:"], ["match_state", "matchState:"],
                          ["match_name", "matchName:"], ["differs", "differs:"]]) {
  check(`toPreviewRows carries ${api}`, rosterMapping.includes(`m.${api}`) && rosterMapping.includes(row),
    "dropped here means the API's answer is computed and then discarded");
}
check("the paste goes through toPreviewRows",
  /"\/api\/roster\/import\/parse"[\s\S]*?toPreviewRows\(result\.members/.test(
    rosterBlock("async function handleParse()", "async function handleCallSheet")),
  "a second mapping for the paste would drop the Roster verdict the way the crew page once did");
check("the call sheet goes through toPreviewRows",
  rosterBlock('"/api/roster/import/call-sheet"', "setPasteRows(rows)").includes("toPreviewRows(result.members"));

console.log("\nRoster: the verdict is shown for a paste too, not only a call sheet");
const tableBlock = rosterBlock("function previewTable(", "function crewEditRow");
check("the status line is keyed on the row's verdict, not on fromSheet",
  tableBlock.includes("r.matchState && importStatusLine(r)") && !tableBlock.includes("fromSheet && importStatusLine"));

console.log("\nRoster: each row is confirmed under its own type");
const rosterConfirm = rosterBlock("async function handleImport()", "async function handleInlineDept");
check("handleImport confirms per type", rosterConfirm.includes("r.type === type")
  && /"\/api\/roster\/import\/confirm",\s*\{\s*type,/.test(rosterConfirm),
  "a call sheet's talent and clients would all be filed under the active tab");

console.log();
console.log(FAILS.length ? `${FAILS.length} FAILURES: ${FAILS.join(", ")}` : "ALL PASS");
process.exit(FAILS.length ? 1 : 0);
