/* The shared social-card image, used by both opengraph-image and twitter-image.
 *
 * Design constraint that drives everything here: this is read at roughly 300px
 * wide in an iMessage or Slack bubble. Anything that isn't the wordmark and one
 * line of plain English is illegible at that size — which is why the previous
 * preview, an app screenshot scraped off the page, read as grey noise.
 *
 * Rendered by Satori, which supports only a subset of CSS: flexbox only, no
 * grid, and every element with more than one child needs an explicit display.
 */
import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const BG = "#0d1117";
const INK = "#e8edf5";
const MUTED = "#9aa5b8";
const ACCENT = "#818cf8";

/** Geist, so the card matches the product. Fetched at build time — and if that
 *  fetch ever fails we render with Satori's default font rather than failing the
 *  whole build for a social image. */
async function geist(weight: number): Promise<ArrayBuffer | null> {
  try {
    const css = await fetch(
      `https://fonts.googleapis.com/css2?family=Geist:wght@${weight}`,
      { headers: { "User-Agent": "Mozilla/5.0 (compatible)" } }
    ).then((r) => r.text());
    const url = /src:\s*url\(([^)]+)\)\s*format\('(?:truetype|opentype)'\)/.exec(css)?.[1];
    if (!url) return null;
    return await fetch(url).then((r) => r.arrayBuffer());
  } catch {
    return null;
  }
}

export async function renderCard() {
  const [bold, regular] = await Promise.all([geist(700), geist(400)]);
  const fonts = [
    bold && { name: "Geist", data: bold, weight: 700 as const, style: "normal" as const },
    regular && { name: "Geist", data: regular, weight: 400 as const, style: "normal" as const },
  ].filter(Boolean) as { name: string; data: ArrayBuffer; weight: 700 | 400; style: "normal" }[];

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          // Centred, not left-aligned: some clients crop toward the middle for
          // small thumbnails, and a left-anchored wordmark loses its first
          // letters when they do.
          alignItems: "center",
          textAlign: "center",
          background: BG,
          // A single soft accent bloom so the card isn't a flat rectangle.
          backgroundImage:
            "radial-gradient(1000px 560px at 50% -18%, rgba(129,140,248,0.20), rgba(13,17,23,0) 64%)",
          padding: "0 96px",
          fontFamily: fonts.length ? "Geist" : "sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            fontSize: 150,
            fontWeight: 700,
            letterSpacing: "-0.045em",
            color: INK,
            lineHeight: 1,
          }}
        >
          <span style={{ display: "flex" }}>SET</span>
          <span style={{ display: "flex", color: ACCENT }}>&gt;</span>
          <span style={{ display: "flex" }}>READY</span>
        </div>

        <div
          style={{
            display: "flex",
            width: 132,
            height: 6,
            background: ACCENT,
            borderRadius: 3,
            margin: "46px 0 42px",
          }}
        />

        {/* Three beats, stacked. Set as separate lines rather than one wrapped
            string so the rhythm survives — and so the last beat, the one nobody
            else does, lands on its own. */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            fontSize: 54,
            fontWeight: 400,
            color: MUTED,
            letterSpacing: "-0.015em",
            lineHeight: 1.35,
          }}
        >
          <span style={{ display: "flex" }}>Plan the day. Tell the crew.</span>
          <span style={{ display: "flex", color: INK }}>Know they got it.</span>
        </div>
      </div>
    ),
    { ...size, fonts: fonts.length ? fonts : undefined }
  );
}
