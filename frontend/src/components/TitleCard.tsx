/* A production company's title card.
 *
 * Typographic, not an image. Almost all of what makes a title card read as one
 * is tracking, restraint and a single colour — a company name set wide on a
 * dark plate is most of the way there, and it needs no upload, no bucket and no
 * file a producer has to go and make. A logo slot belongs here later; the
 * `mark` prop is where it will go.
 *
 * ⚠️ Screen surfaces only. This never enters the stored call sheet HTML, so it
 * cannot reach the email or the PDF — which is exactly why it can use a
 * gradient, a web-safe stack and real letterspacing without worrying about
 * Gmail re-theming it or a printer laying down a solid black band.
 */

interface Props {
  name: string;
  /** #rrggbb, already validated by lib/brand. Undefined falls back to the
   *  app's own accent, which keeps an un-branded account looking deliberate. */
  accent?: string | null;
  /** What this card is sitting on top of — "Call sheet", "Wrap report". */
  kind?: string;
  /** Second line: the project, the date, whatever names this document. */
  subject?: string;
  /** Company artwork, behind everything. Already re-encoded and flattened
   *  server-side onto this card's own plate colour, so it composites cleanly. */
  image?: string | null;
  /** True when the artwork is a finished title card with the company name
   *  already painted into it. Then the card must NOT set the name again —
   *  a real one did exactly that and produced a ghosted double wordmark. */
  nameInImage?: boolean;
  /** Shorter, for a masthead that sits above a working list rather than at the
   *  head of a document. The dashboard is somewhere a producer passes through
   *  many times a day; a full-height card there stops being an arrival and
   *  starts being an obstacle. */
  compact?: boolean;
}

export function TitleCard({ name, accent, kind, subject, image, nameInImage, compact }: Props) {
  const drawName = !(image && nameInImage);
  const rule = accent ?? "var(--accent)";
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        // A plate, not a transparency. The card has to read the same whether
        // it sits on the app's dark chrome or the white confirm page.
        background: "linear-gradient(160deg, #101820 0%, #0a0f15 100%)",
        border: "1px solid rgba(255,255,255,0.07)",
      }}
    >
      <div style={{ height: "3px", background: rule }} />
      <div
        className="relative px-6 text-center"
        style={{
          backgroundImage: image ? `url(${JSON.stringify(image)})` : undefined,
          backgroundSize: "cover",
          backgroundPosition: "center",
          // Taller with artwork: a painting cropped to a two-line strip reads as
          // a texture rather than a picture.
          padding: image
            ? (nameInImage
                ? (compact ? "clamp(46px, 10vw, 84px) 24px" : "clamp(78px, 19vw, 150px) 24px")
                : (compact ? "clamp(34px, 7vw, 58px) 24px" : "clamp(56px, 13vw, 104px) 24px"))
            : undefined,
        }}
      >
        {/* A scrim, not a dimmer. Heaviest at the centre band where the wordmark
            sits and lightest at the edges, so the artwork stays legible as a
            picture while the type keeps its contrast over any part of it —
            including a bright sky, which is exactly where a seascape puts its
            brightest values. */}
        {image && (
          <div
            aria-hidden="true"
            style={{
              position: "absolute", inset: 0,
              // No scrim over artwork that is already a finished title card —
              // there is no type of ours to protect, and dimming it would only
              // damage someone's painting.
              background: nameInImage
                ? "none"
                : "radial-gradient(ellipse 90% 70% at 50% 50%, rgba(6,10,14,0.78) 0%, rgba(6,10,14,0.55) 55%, rgba(6,10,14,0.35) 100%)",
            }}
          />
        )}
        <div className="relative" style={{
          paddingTop: image ? 0 : compact ? "22px" : "32px",
          paddingBottom: image ? 0 : compact ? "22px" : "32px",
        }}>
        {kind && drawName && (
          <p
            className="mb-4"
            style={{
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              fontSize: "10px",
              letterSpacing: "0.24em",
              textTransform: "uppercase",
              color: image ? "rgba(233,227,214,0.7)" : "rgba(233,227,214,0.42)",
              textShadow: image ? "0 1px 10px rgba(0,0,0,0.8)" : undefined,
            }}
          >
            {kind}
          </p>
        )}
        {/* When the artwork carries the name, the text still exists for screen
            readers and for anything that reads the page without rendering it —
            the company's name is information, not decoration, and baking it
            into a JPEG would otherwise lose it entirely. */}
        {!drawName && (
          <span style={{
            position: "absolute", width: 1, height: 1, padding: 0, margin: -1,
            overflow: "hidden", clip: "rect(0,0,0,0)", whiteSpace: "nowrap", border: 0,
          }}>
            {name}{kind ? ` — ${kind}` : ""}
          </span>
        )}
        {drawName && (
        <p
          style={{
            // Wide tracking is the whole effect. The trailing space it adds on
            // the last letter is what text-indent puts back, or the line reads
            // visibly off-centre.
            fontFamily: 'Georgia, "Times New Roman", serif',
            fontWeight: 400,
            fontSize: "clamp(1.5rem, 4.4vw, 2.35rem)",
            letterSpacing: "0.3em",
            textIndent: "0.3em",
            textTransform: "uppercase",
            lineHeight: 1.15,
            color: "#e9e3d6",
            margin: 0,
            wordBreak: "break-word",
            textShadow: image ? "0 2px 24px rgba(0,0,0,0.85)" : undefined,
          }}
        >
          {name}
        </p>
        )}
        {/* Over the artwork only when we drew the wordmark ourselves. If the
            company's own lettering is painted into the image, this line would
            land on top of it — which it did: "Fall 2026" straight across
            SEAWORTHY. Then it belongs in a strip below the picture instead. */}
        {subject && drawName && (
          <p
            className="mt-4"
            style={{
              fontSize: "0.82rem",
              letterSpacing: "0.02em",
              color: image ? "rgba(233,227,214,0.78)" : "rgba(233,227,214,0.55)",
              margin: "16px 0 0",
              textShadow: image ? "0 1px 12px rgba(0,0,0,0.7)" : undefined,
            }}
          >
            {subject}
          </p>
        )}
        </div>
      </div>
      {subject && !drawName && (
        <div
          className="px-6 py-2.5 text-center"
          style={{ borderTop: "1px solid rgba(255,255,255,0.08)", background: "rgba(6,10,14,0.55)" }}
        >
          <span style={{
            fontSize: "10.5px", fontWeight: 500, letterSpacing: "0.16em",
            textTransform: "uppercase", color: "rgba(233,227,214,0.62)",
          }}>
            {kind ? `${kind} · ${subject}` : subject}
          </span>
        </div>
      )}
    </div>
  );
}
