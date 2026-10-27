"use client";

// Our own calendar for picking a job's or a hire's dates, replacing the
// browser's date picker where context tinting matters (docs/job-layer-plan.md
// §7). Picking replaces the block being edited rather than stacking a second
// one by accident; "+ Separate block" is how a producer adds a deliberate gap
// (two shoot stretches, say).
//
// Every button here is type="button": the New job page puts this calendar
// inside a <form>, where a bare <button> submits — flipping to next month
// once created the job.

import { useState } from "react";
import { DAY_TYPES, DayType, displaySpan, LABELS, monthGrid, noneLabel, Span, toIso } from "@/lib/jobDates";
import { DayTypeTag } from "@/components/DayType";

interface Props {
  dayType: DayType;
  /** Every day type's blocks for the person being edited (or the crew, when
   *  editing the Whole crew row) — used to tint days that belong to a
   *  DIFFERENT type than the one open, and to know what "mine" means. */
  getBlocks: (t: DayType) => Span[];
  /** When editing a hire's cell: the crew's own blocks for this type, shown
   *  as a ring so it's visible how far a custom date sits from the crew's. */
  crewBlocks?: Span[];
  initialMonth: string;
  suggestedDate?: string | null;
  range: boolean;
  onCommit: (first: string, last: string, append: boolean) => void;
  onRemove: (index: number) => void;
  onReset?: () => void;
  who: string;
  isCrewRow: boolean;
  /** "+ Separate block" — two stretches of one day type with a gap. On by
   *  default; off where one span is the whole answer (creating a job). */
  allowSeparate?: boolean;
  /** "No <type>" — records that the crew has none of this day type (a local
   *  job with no travel), so setup can move past it. Only offered while
   *  nothing is set. */
  onNone?: () => void;
}

/** One day, "Sun, Oct 4" — the same form displaySpan uses for a single day. */
function longDate(iso: string): string {
  return displaySpan(iso, iso);
}
function monthTitle(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
}
function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return toIso(d).slice(0, 7);
}

export function RangeCalendar({
  dayType, getBlocks, crewBlocks, initialMonth, suggestedDate, range,
  onCommit, onRemove, onReset, who, isCrewRow, allowSeparate = true, onNone,
}: Props) {
  const [month, setMonth] = useState(initialMonth);
  const [start, setStart] = useState<string | null>(null);
  const [append, setAppend] = useState(false);
  const [hover, setHover] = useState<string | null>(null);

  const current = getBlocks(dayType);
  const days = monthGrid(month);

  function typeOwning(day: string): DayType | null {
    for (const t of DAY_TYPES) {
      for (const [a, b] of getBlocks(t)) if (day >= a && day <= b) return t;
    }
    return null;
  }

  function pick(day: string) {
    if (!range) { onCommit(day, day, append); setStart(null); return; }
    if (!start || day < start) { setStart(day); return; }
    onCommit(start, day, append);
    setStart(null);
  }

  const otherTypesPresent = DAY_TYPES.filter((t) => t !== dayType && getBlocks(t).length > 0);

  return (
    <div>
      <div className="flex items-start justify-between gap-2 mb-2.5">
        <div>
          <div className="flex items-center gap-2 flex-wrap text-[13px] font-semibold" style={{ color: "var(--text-primary)" }}>
            <DayTypeTag type={dayType} />
            <span>{who}</span>
          </div>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
            {range ? (start ? "Now pick the last day" : append ? "Pick the first day of the separate block" : "Pick the first day") : "Pick a day"}
            {!isCrewRow ? ` · changes ${who.split(" ")[0]} only` : ""}
          </p>
        </div>
      </div>

      {!isCrewRow && crewBlocks && crewBlocks.length > 0 && (
        <p className="text-xs mb-2.5" style={{ color: "var(--text-secondary)" }}>
          Crew: <b className="date-text" style={{ color: "var(--text-primary)" }}>
            {crewBlocks.map(([a, b]) => displaySpan(a, b)).join(", ")}
          </b>
        </p>
      )}

      {current.length > 0 && (
        <div className="grid gap-1 mb-2.5 p-2 rounded-lg" style={{ background: "var(--bg-inset)" }}>
          {current.map(([a, b], i) => (
            <div key={i} className="flex items-center justify-between gap-2 text-xs">
              <span className="date-text" style={{ color: "var(--text-primary)" }}>
                {displaySpan(a, b)}
              </span>
              <button type="button"
                onClick={() => onRemove(i)}
                className="text-xs px-1.5 py-0.5 rounded"
                style={{ color: "var(--text-secondary)" }}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between mb-1.5">
        <button type="button" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month" className="w-7 h-7 rounded-md text-base" style={{ color: "var(--text-secondary)" }}>‹</button>
        <span className="text-[13px] font-semibold" style={{ color: "var(--text-primary)" }}>{monthTitle(month)}</span>
        <button type="button" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Next month" className="w-7 h-7 rounded-md text-base" style={{ color: "var(--text-secondary)" }}>›</button>
      </div>

      <div className="cal-grid" onMouseLeave={() => setHover(null)}>
        {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => <span key={i} className="cal-dow">{d}</span>)}
        {days.map((day) => {
          const t = typeOwning(day);
          const classes = ["cal-day"];
          if (!day.startsWith(month)) classes.push("out");
          if (t) { classes.push(`tint-${t}`); if (t === dayType) classes.push("mine"); }
          if (!isCrewRow && crewBlocks?.some(([a, b]) => day >= a && day <= b)) classes.push("crew-mark");
          if (day === suggestedDate && !start) classes.push("suggest");
          if (start && day === start) classes.push("start");
          if (start && range && hover && day > start && day <= hover) classes.push("preview");
          return (
            <button
              key={day}
              type="button"
              className={classes.join(" ")}
              onClick={() => pick(day)}
              onMouseEnter={() => setHover(day)}
              aria-label={longDate(day)}
            >
              {Number(day.slice(8, 10))}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 mt-2.5 pt-2.5" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="flex flex-wrap gap-x-2.5 gap-y-1 text-[11px]" style={{ color: "var(--text-secondary)" }}>
          {otherTypesPresent.map((t) => (
            <span key={t} className="inline-flex items-center gap-1">
              <i className="inline-block w-2 h-2 rounded" style={{ background: `var(--day-${t === "travel_out" ? "travel" : t})` }} />
              {LABELS[t]}
            </span>
          ))}
          {!isCrewRow && crewBlocks && crewBlocks.length > 0 && (
            <span className="inline-flex items-center gap-1">
              <i className="inline-block w-2 h-2 rounded" style={{ boxShadow: "inset 0 0 0 1.5px var(--text-muted)" }} />
              Crew
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {range && start && (
            <button type="button" onClick={() => { onCommit(start, start, append); setStart(null); }} className="btn btn-ghost btn-sm" style={{ border: "1px solid var(--border-strong)" }}>
              Just {longDate(start)}
            </button>
          )}
          {allowSeparate && range && current.length > 0 && !start && (
            <button type="button"
              onClick={() => setAppend((a) => !a)}
              className="btn btn-ghost btn-sm"
              style={{
                border: "1px solid var(--border-strong)",
                background: append ? "var(--accent-subtle)" : undefined,
                color: append ? "var(--accent-text)" : undefined,
              }}
            >
              + Separate block
            </button>
          )}
          {onNone && current.length === 0 && !start && (
            <button type="button" onClick={onNone} className="btn btn-ghost btn-sm" style={{ border: "1px solid var(--border-strong)" }}>
              {noneLabel(dayType)}
            </button>
          )}
          {onReset && (
            <button type="button" onClick={onReset} className="btn btn-ghost btn-sm" style={{ border: "1px solid var(--border-strong)" }}>
              Reset to crew dates
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
