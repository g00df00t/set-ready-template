"use client";

import { useEffect, useRef, useState } from "react";

// The generated sheet is laid out at a fixed 680px — its tables don't reflow,
// which is why the confirm page used to force a sideways scroll instead.
const SHEET_WIDTH = 680;

/**
 * Renders a call sheet scaled down to fit its container instead of overflowing.
 *
 * This is what Gmail already does to the same HTML in the email, which is why
 * the sheet reads fine there and ran off the screen here. Uses `zoom` rather
 * than `transform: scale()` so the surrounding page picks up the reduced
 * height — a transform would leave a tall gap underneath. Never scales up, so
 * on a desktop the sheet stays at its intended size.
 */
export function FitSheet({ html }: { html: string }) {
  const holder = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = holder.current;
    if (!el) return;
    const fit = () => {
      const available = el.clientWidth;
      if (available > 0) setScale(Math.min(1, available / SHEET_WIDTH));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    // Hidden overflow so the first frame — rendered before the effect measures —
    // can't flash a horizontal scrollbar.
    // Centred, because the inner box is a fixed 680px: on any screen wider than
    // that it does not scale, and without this it sat hard left with the rest of
    // the row as dead space. The sheet's own `margin: 0 auto` cannot do it —
    // its parent is exactly its own width, so there is nothing to centre within.
    <div ref={holder} style={{ overflow: "hidden", display: "flex", justifyContent: "center" }}>
      <div
        style={{
          width: `${SHEET_WIDTH}px`,
          zoom: scale,
          background: "#fff",
          borderRadius: "12px",
          overflow: "hidden",
        }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
