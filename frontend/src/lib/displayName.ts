/* The producer's display name, as the account page previews it.
 *
 * This deliberately mirrors backend/auth.py's _clean_display_name. The backend
 * is the one that matters — user_metadata can be written straight through
 * Supabase's auth API without this page ever loading, so the server cleans it
 * again regardless of what happens here.
 *
 * This copy exists so the preview tells the truth. A producer typing "Pat" needs
 * to see exactly what their crew will receive; a preview that disagrees with the
 * result is worse than no preview at all.
 *
 * ⚠️ If you change one, change the other. Both are tested against the same
 * cases — frontend/tests/display-name.test.ts and backend/tests/test_display_name.py.
 */

export const NAME_MAX = 80;

/** Whitespace collapses to single spaces, unprintables disappear, length is
 *  capped. Returns null when nothing usable is left. */
export function cleanDisplayName(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") return null;
  // Whitespace first, and the order matters: split() treats tabs, newlines and
  // returns alike so each becomes one space and word boundaries survive.
  // Removing them first would weld words together — "Pat<tab>Kehoe" → "PatKehoe".
  const collapsed = raw.split(/\s+/).filter(Boolean).join(" ");
  // Then drop what cannot be printed. These are not separators, so deleting them
  // is right. \p{C} is Unicode "Other" — control, format, surrogate, private use
  // and unassigned — which is what Python's str.isprintable() rejects too.
  const printable = collapsed.replace(/\p{C}/gu, "");
  const capped = printable.slice(0, NAME_MAX).trim();
  return capped || null;
}

/** Exactly what a crew member sees in the From line of their call sheet. */
export function fromLine(raw: string | null | undefined): string {
  const name = cleanDisplayName(raw);
  return name ? `${name} via Set Ready` : "Set Ready";
}
