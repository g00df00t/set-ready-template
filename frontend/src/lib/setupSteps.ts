/* The setup order — defined once, here, and nowhere else.
 *
 * Three surfaces need to agree on what order a project gets built in: the
 * sidebar in projects/[id]/layout.tsx, the checklist on the overview, and the
 * "next" prompt at the foot of each page. They have already drifted apart once —
 * Accommodations and Meal Plan were added to the sidebar but not the checklist,
 * so following the checklist skipped two sections and the sidebar highlight
 * jumped two places. Adding a third hardcoded list would reintroduce that bug,
 * so the checklist and the next-prompt both read this array.
 *
 * The order matches the sidebar, which is ordered by where each section lands on
 * the finished call sheet. If a section moves on the sheet, move it here too.
 *
 * `optional` steps still appear in the sequence and can be completed — they just
 * never hold the setup checklist open. Plenty of jobs have no talent, no agency
 * contact, no hotel and no catering.
 */

export interface SetupStep {
  /** Path under /projects/[id] — also the key used to locate the current page. */
  path: string;
  /** Imperative, for the checklist: this is a task. */
  task: string;
  /** The destination's own name, for "Next: …". */
  name: string;
  optional?: boolean;
}

export const SETUP_STEPS: SetupStep[] = [
  { path: "/crew",           task: "Add your crew",            name: "Crew" },
  { path: "/talent",         task: "Add talent",               name: "Talent",          optional: true },
  { path: "/contacts",       task: "Add agency & clients",     name: "Agency & Client", optional: true },
  { path: "/location",       task: "Set your location",        name: "Location" },
  { path: "/meals",          task: "Set the meal plan",        name: "Meal Plan",       optional: true },
  { path: "/accommodations", task: "Add accommodations",       name: "Accommodations",  optional: true },
  { path: "/schedule",       task: "Build your schedule",      name: "Schedule" },
  { path: "/call-sheet",     task: "Generate your call sheet", name: "Call Sheet" },
];

/** The step after `path`, or null at the end of the sequence — and for pages
 *  that aren't part of setup at all (the overview, Notes), which is why these
 *  return null rather than falling back to either end of the list. */
export function nextStepAfter(path: string): SetupStep | null {
  const i = SETUP_STEPS.findIndex((s) => s.path === path);
  if (i === -1 || i === SETUP_STEPS.length - 1) return null;
  return SETUP_STEPS[i + 1];
}

/** The step before `path`, or null at the start of the sequence. */
export function prevStepBefore(path: string): SetupStep | null {
  const i = SETUP_STEPS.findIndex((s) => s.path === path);
  if (i <= 0) return null;
  return SETUP_STEPS[i - 1];
}
