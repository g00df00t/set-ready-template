/* A producer's company brand: a name, and one colour.
 *
 * Deliberately two fields. Most of what makes a title card read as a title card
 * is tracking, restraint and a good colour — none of which need an uploaded
 * file — so this ships before any storage bucket exists and tells us whether
 * the rest is worth building. A logo slot comes later; nothing here forecloses it.
 *
 * Stored in Supabase user_metadata, the same place the sender display name
 * lives, which is why this needs no migration.
 *
 * An earlier version used the accent to repaint the whole app — every button,
 * focus ring and active nav item — by overriding the CSS variables globals.css
 * already drew them from. That was reverted; the colour now only draws the rule
 * across the top of a title card. The machinery is gone rather than dormant,
 * but the approach is worth remembering: it was four variables, and it worked.
 *
 * ⚠️ The accent lands in a style attribute, so `isBrandColor` is a security
 * boundary and not a nicety. Anything that isn't exactly #rrggbb is refused
 * rather than sanitised — there is no half-valid colour worth rescuing.
 */

export interface Brand {
  name: string | null;
  accent: string | null;
  /** Title-card artwork. Only ever a URL the backend issued into our own public
   *  bucket — see isBrandImage. */
  image: string | null;
  /** The artwork is a finished title card and already shows the company name. */
  nameInImage: boolean;
  /** Plain artwork with no typography, for the page mastheads to sit over.
   *  Separate from `image` because the two surfaces want different pictures:
   *  a title card fronts a document, a background sits under a page title. */
  background: string | null;
}

export const BRAND_NAME_MAX = 40;

/** Strict #rrggbb. No shorthand, no named colours, no rgb() — a style attribute
 *  is not the place to be accommodating. */
export function isBrandColor(value: unknown): value is string {
  return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
}

/** One line, bounded, or nothing.
 *
 * Mirrors cleanDisplayName in lib/displayName.ts, including the order that
 * matters: collapse whitespace FIRST so a tab becomes a space and word
 * boundaries survive, then drop what can't be printed. Doing it the other way
 * welds words together — "Sea\tworthy" became "Seaworthy" in the display-name
 * version, and a test caught it there. Shorter cap here: 80 characters is a
 * From line, 40 is as much as a letterspaced title card can hold. */
export function cleanBrandName(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const collapsed = raw.split(/\s+/).filter(Boolean).join(" ");
  // \p{C} is control, format, surrogate, private-use and unassigned — the same
  // set Python's str.isprintable() rejects, and the same expression
  // lib/displayName.ts uses. Everything printable stays, so accents,
  // apostrophes and non-Latin scripts survive in a company name.
  const printable = collapsed.replace(/\p{C}/gu, "");
  const trimmed = printable.slice(0, BRAND_NAME_MAX).trim();
  return trimmed || null;
}

/** What a session's user_metadata says the brand is. Unset and invalid are the
 *  same answer — null — because a half-applied brand looks like a bug. */
export function readBrand(metadata: Record<string, unknown> | null | undefined): Brand {
  const meta = metadata ?? {};
  return {
    name: cleanBrandName(meta.brand_name),
    accent: isBrandColor(meta.brand_accent) ? (meta.brand_accent as string).toLowerCase() : null,
    image: isBrandImage(meta.brand_image_url) ? (meta.brand_image_url as string) : null,
    nameInImage: meta.brand_image_has_name === true,
    background: isBrandImage(meta.brand_background_url) ? (meta.brand_background_url as string) : null,
  };
}

/** Only a public object in our own brand bucket.
 *
 * The value round-trips through user_metadata, so by the time anything reads it
 * back it could be any string. It lands in a CSS url() and, on the confirm
 * page, in front of crew who have no account — so it is checked against the
 * Supabase origin we issued it from rather than trusted. Mirrors _is_our_asset
 * in backend/auth.py, which does the same check for the surfaces that have no
 * session at all. */
export function isBrandImage(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const base = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!base) return false;
  return value.startsWith(`${base.replace(/\/$/, "")}/storage/v1/object/public/brand-assets/`)
    && !/[\s"'\\)]/.test(value);
}
