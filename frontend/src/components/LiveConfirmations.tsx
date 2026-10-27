"use client";

import { useEffect, useState } from "react";

const CREW = [
  { name: "Maya Okafor", role: "1st AD" },
  { name: "Devon Cole", role: "Gaffer" },
  { name: "Priya Raman", role: "Hair & Makeup" },
];

const TOTAL = 9;        // total crew on the call sheet
const BASE = TOTAL - CREW.length; // confirmed crew not shown in the list

// Timeline (ms): flip each visible row, hold, fade, then loop.
const STEPS = [1200, 2500, 3800];
const HOLD = 6800;
const RESET = 7300;

export default function LiveConfirmations({ scale = 1 }: { scale?: number }) {
  const s = (n: number) => `${n * scale}px`;
  const [confirmed, setConfirmed] = useState(0); // # of visible rows confirmed
  const [fading, setFading] = useState(false);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduce) {
      setConfirmed(CREW.length);
      return;
    }

    const timers: ReturnType<typeof setTimeout>[] = [];
    const run = () => {
      setConfirmed(0);
      STEPS.forEach((t, i) => timers.push(setTimeout(() => setConfirmed(i + 1), t)));
      timers.push(setTimeout(() => setFading(true), HOLD));
      timers.push(
        setTimeout(() => {
          setFading(false);
          run();
        }, RESET),
      );
    };
    run();

    return () => timers.forEach(clearTimeout);
  }, []);

  const total = BASE + confirmed;
  const pct = Math.round((total / TOTAL) * 100);

  return (
    <div
      style={{
        maxWidth: s(420),
        margin: `${s(48)} 0 0`,
        textAlign: "left",
        background: "var(--bg-surface)",
        border: "1px solid var(--border)",
        borderRadius: s(14),
        padding: `${s(18)} ${s(20)}`,
        boxShadow: "0 16px 40px var(--shadow-color)",
        opacity: fading ? 0 : 1,
        transition: "opacity 0.4s ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: s(16) }}>
        <div style={{ display: "flex", alignItems: "center", gap: s(8) }}>
          <span className="live-dot" style={{ width: s(8), height: s(8) }} />
          <span style={{ fontSize: s(11), fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--success)" }}>
            Live · Crew confirmations
          </span>
        </div>
        <span style={{ fontSize: s(12), fontWeight: 600, color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }}>
          {total} / {TOTAL} confirmed
        </span>
      </div>

      {/* Progress bar */}
      <div style={{ height: s(5), borderRadius: "999px", background: "var(--bg-elevated)", overflow: "hidden", marginBottom: s(18) }}>
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: "999px",
            background: "var(--success)",
            transition: "width 0.6s cubic-bezier(0.22, 1, 0.36, 1)",
          }}
        />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: s(12) }}>
        {CREW.map((c, i) => {
          const isConfirmed = i < confirmed;
          return (
            <div key={c.name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: s(13), fontWeight: 600 }}>{c.name}</div>
                <div style={{ fontSize: s(12), color: "var(--text-muted)" }}>{c.role}</div>
              </div>
              {isConfirmed ? (
                <span
                  key="confirmed"
                  className="confirm-pill"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: s(5),
                    fontSize: s(12),
                    fontWeight: 600,
                    color: "var(--success)",
                    background: "var(--success-subtle)",
                    padding: `${s(3)} ${s(10)}`,
                    borderRadius: "999px",
                  }}
                >
                  <span aria-hidden>✓</span> Confirmed
                </span>
              ) : (
                <span
                  style={{
                    fontSize: s(12),
                    fontWeight: 600,
                    color: "var(--text-muted)",
                    background: "var(--bg-elevated)",
                    padding: `${s(3)} ${s(10)}`,
                    borderRadius: "999px",
                  }}
                >
                  Pending
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
