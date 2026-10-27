// Travel in / Prep-Scout / Shoot day / Wrap day / Travel out, colored consistently
// everywhere a day type appears. See globals.css's ".day-tag"/".day-pill" for
// the colors themselves (jobs design system, docs/job-layer-plan.md §7).

import { DayType, LABELS } from "@/lib/jobDates";

/** A dot + label, for a table header or a calendar legend. */
export function DayTypeTag({ type, label }: { type: DayType; label?: string }) {
  return <span className={`day-tag day-tag-${type}`}>{label ?? LABELS[type]}</span>;
}

/** A filled chip, for a timeline entry or a quick-add choice. */
export function DayTypePill({ type, label }: { type: DayType; label?: string }) {
  return <span className={`day-pill day-pill-${type}`}>{label ?? LABELS[type]}</span>;
}
