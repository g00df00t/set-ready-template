"use client";

import { useEffect, useState } from "react";

// Each person carries both representations: the messy line as pasted from a PDF
// call sheet, and the clean structured fields Claude parses out. The animation
// morphs raw → parsed in place, one line at a time, as the point sweeps past.
const PEOPLE = [
  { raw: "PA Marco Reyes marco.reyes@example.com 360-555-0142 11:00 AM Woodinville Farmhouse", name: "Marco Reyes", role: "PA", email: "marco.reyes@example.com", phone: "360-555-0142" },
  { raw: "PA Dana Whitfield dana.w@example.com 206-555-7195 11:30 AM Crew Holding Lot - Hollywood", name: "Dana Whitfield", role: "PA", email: "dana.w@example.com", phone: "206-555-7195" },
  { raw: "Shuttle Driver Sam Okonkwo sam.okonkwo@example.com 206.555-1958 11:30 AM Crew Holding Lot", name: "Sam Okonkwo", role: "Shuttle Driver", email: "sam.okonkwo@example.com", phone: "206-555-1958" },
  { raw: "Media Mgmt Priya Anand priya.anand@example.com 206.555.5442 11:00 AM Woodinville", name: "Priya Anand", role: "Media Management", email: "priya.anand@example.com", phone: "206-555-5442" },
  { raw: "H&M Robin Mercer robin.mercer@example.com 360-555-2432 11:30 AM Crew Holding Lot - Hollywood", name: "Robin Mercer", role: "Hair & Makeup", email: "robin.mercer@example.com", phone: "360-555-2432" },
  { raw: "Gaffer T. Vance t.vance@example.com 206.555.0134 6:30A Stage 4 / Hollywood Vineyards", name: "Tomas Vance", role: "Gaffer", email: "t.vance@example.com", phone: "206-555-0134" },
];

const N = PEOPLE.length;
const COLS = "1.05fr 1.1fr 1.5fr 0.85fr";

type Phase = "paste" | "transform";

export default function QuickImportDemo({ scale = 1 }: { scale?: number }) {
  const s = (n: number) => `${n * scale}px`;
  const [phase, setPhase] = useState<Phase>("paste");
  const [pastedLines, setPastedLines] = useState(0);   // raw lines landed
  const [parsedCount, setParsedCount] = useState(0);   // lines morphed to clean
  const [fading, setFading] = useState(false);

  const pasteStep = 230;            // ms between raw lines landing under the point
  const transformStep = 180;        // ms between line morphs
  const holdMessyMs = 1600;         // dwell on the fully-visible messy paste
  const pasteSweepMs = 250 + N * pasteStep;
  const pasting = phase === "paste" && pastedLines < N;
  const transforming = phase === "transform" && parsedCount < N;
  const done = phase === "transform" && parsedCount >= N;

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduce) {
      setPhase("transform");
      setPastedLines(N);
      setParsedCount(N);
      return;
    }

    const timers: ReturnType<typeof setTimeout>[] = [];
    const run = () => {
      setFading(false);
      setPhase("paste");
      setPastedLines(0);
      setParsedCount(0);

      // The point sweeps top-left → bottom-right, dragging in the messy paste.
      PEOPLE.forEach((_, i) => timers.push(setTimeout(() => setPastedLines(i + 1), 250 + i * pasteStep)));

      // Dwell on the visible messy text, then morph each line to clean (no point).
      const transformStart = pasteSweepMs + holdMessyMs;
      timers.push(setTimeout(() => setPhase("transform"), transformStart));
      PEOPLE.forEach((_, i) => timers.push(setTimeout(() => setParsedCount(i + 1), transformStart + 150 + i * transformStep)));
      const doneEnd = transformStart + 150 + N * transformStep;

      const holdEnd = doneEnd + 2800;
      timers.push(setTimeout(() => setFading(true), holdEnd));
      timers.push(setTimeout(() => run(), holdEnd + 650));
    };
    run();

    return () => timers.forEach(clearTimeout);
  }, []);

  const status = phase === "paste" ? "Pasting…" : transforming ? "Reading…" : `✓ ${N} people found`;
  const statusColor = done ? "var(--success)" : phase === "transform" ? "var(--accent-hover)" : "var(--text-muted)";
  const dotColor = done ? "var(--success)" : "var(--accent)";

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        maxWidth: s(560),
        background: "var(--bg-surface)",
        border: "1px solid var(--border)",
        borderRadius: s(14),
        overflow: "hidden",
        boxShadow: "0 16px 40px var(--shadow-color)",
        textAlign: "left",
        display: "flex",
        flexDirection: "column",
        height: s(306),
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: `${s(11)} ${s(16)}`,
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: s(8) }}>
          <span style={{ width: s(8), height: s(8), borderRadius: "50%", background: dotColor, transition: "background 0.3s ease" }} />
          <span style={{ fontSize: s(12), fontWeight: 700 }}>{phase === "paste" ? "Paste crew data" : "Review & import"}</span>
        </div>
        <span style={{ fontSize: s(12), fontWeight: 600, color: statusColor, fontVariantNumeric: "tabular-nums", transition: "color 0.3s ease" }}>
          {status}
        </span>
      </div>

      {/* Body */}
      <div style={{ position: "relative", flex: 1, minHeight: 0, padding: `${s(8)} ${s(12)}`, overflow: "hidden" }}>
        {/* Top strip: file label (paste) → column header (parsed) */}
        <div style={{ position: "relative", height: s(18), marginBottom: s(6) }}>
          <div style={{ position: "absolute", inset: 0, opacity: phase === "paste" ? 1 : 0, transition: "opacity 0.3s ease", fontSize: s(10), fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            📄 call_sheet.pdf
          </div>
          <div style={{ position: "absolute", inset: 0, opacity: phase === "paste" ? 0 : 1, transition: "opacity 0.3s ease", display: "grid", gridTemplateColumns: COLS, gap: s(10), padding: `0 ${s(10)}`, fontSize: s(10), fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
            <span>Name</span><span>Role</span><span>Email</span><span>Phone</span>
          </div>
        </div>

        {/* Slots — each morphs raw → parsed in place */}
        <div style={{ display: "flex", flexDirection: "column", gap: s(1) }}>
          {PEOPLE.map((p, i) => {
            const parsed = i < parsedCount;
            return (
              <div key={p.name} style={{ position: "relative", height: parsed ? s(28) : s(20), transition: "height 0.35s cubic-bezier(0.22, 1, 0.36, 1)" }}>
                {/* Raw line */}
                <div
                  style={{
                    position: "absolute", inset: 0, display: "flex", alignItems: "center", padding: `0 ${s(10)}`,
                    fontFamily: "var(--font-mono, monospace)", fontSize: s(11.5), color: "var(--text-secondary)",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    opacity: parsed ? 0 : i < pastedLines ? 1 : 0,
                    transition: "opacity 0.35s ease",
                  }}
                >
                  {p.raw}
                </div>
                {/* Parsed row (wipes in left→right over the raw) */}
                {parsed && (
                  <div
                    className="qi-row-in"
                    style={{
                      position: "absolute", inset: 0, display: "grid", gridTemplateColumns: COLS, gap: s(10),
                      alignItems: "center", padding: `0 ${s(10)}`, borderRadius: s(6),
                      background: i % 2 ? "transparent" : "var(--bg-elevated)",
                    }}
                  >
                    <span style={{ fontSize: s(12.5), fontWeight: 600, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span>
                    <span style={{ fontSize: s(12), color: "var(--text-secondary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.role}</span>
                    <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: s(11.5), color: "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.email}</span>
                    <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: s(11.5), color: "var(--text-secondary)", whiteSpace: "nowrap" }}>{p.phone}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Paste "cursor" — sweeps top-left → bottom-right, dragging in the messy text */}
        {pasting && (
          <span
            className="qi-point"
            style={{
              position: "absolute",
              width: s(10), height: s(10), borderRadius: "50%",
              background: "var(--text-secondary)",
              boxShadow: `0 0 ${s(11)} ${s(2)} var(--text-muted)`,
              pointerEvents: "none",
              animationDuration: `${pasteSweepMs / 1000}s`,
            }}
          />
        )}
      </div>

      {/* Footer — faux import action, mirrors the in-app preview */}
      <div style={{ padding: `${s(10)} ${s(16)}`, borderTop: "1px solid var(--border)", display: "flex", alignItems: "center" }}>
        <span
          style={{
            fontSize: s(12), fontWeight: 600, color: "#fff",
            background: "var(--accent)", padding: `${s(7)} ${s(14)}`, borderRadius: s(8),
            opacity: done ? 1 : 0.55,
            transition: "opacity 0.3s ease",
          }}
        >
          {phase === "transform" ? `Import ${N} people` : "Import"}
        </span>
      </div>

      {/* Fade veil between loops */}
      <div
        style={{
          position: "absolute", inset: 0, background: "var(--bg-surface)",
          opacity: fading ? 1 : 0, transition: "opacity 0.45s ease",
          pointerEvents: "none",
        }}
      />
    </div>
  );
}
