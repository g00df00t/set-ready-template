"use client";

// A floating panel anchored under a trigger element — the Crew & dates
// table's date-picker popover, and anything else in the Jobs screens that
// needs one. Positioned relative to `containerRef` (must be `position:
// relative` or the nearest positioned ancestor), not the viewport, so it
// scrolls with the table rather than the page.

import { useEffect, useLayoutEffect, useRef, useState } from "react";

interface Props {
  anchorRef: React.RefObject<HTMLElement | null>;
  containerRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
  ariaLabel: string;
  width?: number;
  children: React.ReactNode;
}

export function Popover({ anchorRef, containerRef, onClose, ariaLabel, width = 300, children }: Props) {
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    function place() {
      const anchor = anchorRef.current, container = containerRef.current, pop = popRef.current;
      if (!anchor || !container) return;
      const cr = container.getBoundingClientRect(), ar = anchor.getBoundingClientRect();
      const popWidth = pop?.offsetWidth ?? width;
      const maxLeft = Math.max(8, container.clientWidth - popWidth - 8);
      setPos({
        left: Math.max(8, Math.min(ar.left - cr.left, maxLeft)),
        top: ar.bottom - cr.top + 8,
      });
    }
    place();
    window.addEventListener("resize", place);
    // Capture phase: a scroll fired on an inner overflow-x:auto element (the
    // table wrapper) doesn't bubble, but a capturing listener on window still
    // sees it on the way down, so this repositions on both page scroll and
    // the table's own horizontal scroll without needing a second ref.
    window.addEventListener("scroll", place, true);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(place) : null;
    if (containerRef.current) ro?.observe(containerRef.current);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      ro?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorRef, containerRef, width]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      if (popRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") { onClose(); anchorRef.current?.focus(); }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [anchorRef, onClose]);

  return (
    <div
      ref={popRef}
      role="dialog"
      aria-label={ariaLabel}
      className="popover-surface"
      style={{
        position: "absolute", zIndex: 20, width, maxWidth: "calc(100% - 16px)", padding: "0.875rem",
        left: pos?.left ?? 0, top: pos?.top ?? 0,
        visibility: pos ? "visible" : "hidden",
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>
  );
}
