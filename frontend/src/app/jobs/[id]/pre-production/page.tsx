"use client";

/* Job home, Pre-production tab (docs/job-layer-plan.md §7). Two parts: the
 * Job details card (who it's for, and the crew's dates — the only place
 * those are edited), then Deal Memos: the "Sheet" table of the people hired,
 * each showing the crew's dates unless they have their own, and the
 * downloads. Other pre-production tools join Deal Memos later, at which point
 * the tab grows a sidebar like the day workspace's.
 */

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DayTypeTag } from "@/components/DayType";
import { DateText } from "@/components/DateText";
import { Popover } from "@/components/Popover";
import { RangeCalendar } from "@/components/RangeCalendar";
import { HireForm } from "@/components/HireForm";
import { RateEditor, RateSave } from "@/components/RateEditor";
import { useToast } from "@/components/Toast";
import { useAutosaveField, SaveStatusDot } from "@/lib/useAutosaveField";
import { triggerDownload } from "@/lib/download";
import { RateSuggestion, cleanAmount, hasRates, num, rateLines } from "@/lib/rates";
import {
  CORE_TYPES, DAY_TYPES, DatesByType, DayType, LABELLED_TYPES, LABELS, OTHER_TYPES, Span, TALENT_OTHER_TYPES, TALENT_TYPES, baseDates, datesIn, addDays, displaySpan, effectiveDates, isCustom, nextCrewType,
  noneLabel, sameSpans, sortSpans, spanDays, suggestFor,
} from "@/lib/jobDates";

interface Job {
  id: string;
  name: string;
  client_name: string | null;
  production_company: string | null;
  payroll_provider: string | null;
  // The deal memo's Location and Per Diem lines.
  location_line: string | null;
  per_diem_line: string | null;
  // Per diem a day (supabase/rates_v1.sql). With neither amount set, the memo
  // still prints per_diem_line.
  per_diem_shoot: number | null;
  per_diem_other: number | null;
  per_diem_paid_by: string | null;
  // {ISO date: "Brand A – Studio, NJ"}: the work that day, after that date's
  // prep/shoot/down/wrap lines on every deal memo.
  day_labels?: Record<string, string>;
  // The job's role checklist (backend services/holds.py): each Open, Not
  // needed, or filled by a hire.
  role_slots?: RoleSlot[];
  crew_dates: DatesByType;
}

interface RoleSlot { id: string; role: string; state: "open" | "not_needed"; hire_id: string | null }

// Mirrors backend services/holds.DEFAULT_ROLES — her Crew Holds sheet's rows.
const USUAL_ROLES = ["Producer", "Photographer", "Photo Assist 1st", "Photo Assist 2nd", "Digital Tech",
  "Videographer", "Stylist", "Styling Assist", "HMU", "Set Designer/Props"];

type StatusChoice = "confirmed" | "hold1" | "hold2" | "released";
const statusChoice = (h: { status?: string; hold_rank?: number | null }): StatusChoice =>
  h.status === "hold" ? (h.hold_rank === 2 ? "hold2" : "hold1") : h.status === "released" ? "released" : "confirmed";
const STATUS_LABEL: Record<StatusChoice, string> = { confirmed: "Confirmed", hold1: "1st hold", hold2: "2nd hold", released: "Released" };

interface HireConflict { type: DayType; reason: string }
interface Hire {
  id: string;
  roster_id: string | null;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  department: string | null;
  dates_override: DatesByType;
  // Printed under their generated date lines on the memo.
  dates_note: string | null;
  // {ISO date: text}: their own note on that date's line.
  day_notes?: Record<string, string>;
  // Every date they have, once, as the API sees it (job_dates.person_days).
  person_days?: { date: string; types: DayType[]; label: string | null; note: string | null }[];
  custom: boolean;
  effective_dates: DatesByType;
  conflicts: HireConflict[];
  days: { id: string; name: string; shoot_date: string | null }[];
  // The agreed deal — producer-only, printed on the deal memo and nowhere else.
  rate_shoot: number | null;
  rate_travel: number | null;
  rate_prep: number | null;
  rate_note: string | null;
  rate_source: "job" | "roster" | null;
  rate_source_job_name?: string | null;
  // Offered by the API for anyone without rates yet.
  rate_suggestion?: RateSuggestion | null;
  // hold (1st/2nd) → confirmed, or released. Missing = confirmed.
  status?: "hold" | "confirmed" | "released";
  hold_rank?: number | null;
  // Talent are hires too (backend talent_hires.sql): their hold-sheet
  // segment, the agency's fee on top of the rate, notes, and — read live from
  // the Roster — agency, agent, home city and portfolio link.
  kind?: "crew" | "talent";
  segment?: string | null;
  agency_fee_pct?: number | null;
  notes?: string | null;
  talent_info?: { agency: string | null; agent: string | null; based: string | null; portfolio_url: string };
}

// Only single-day types get "Just <date>"'s sibling behavior of committing
// immediately on the first click — matches the deal-memos page's own picker
// and backend job_dates.py's DAY_TYPES ordering.
const RANGE_TYPES = new Set<DayType>(["prep", "shoot", "off", "wrap"]);

// What the Next bar asks while walking the crew's dates.
// Check-in and Down day are never asked: only some jobs have them.
const ASK: Partial<Record<DayType, string>> = {
  shoot: "Set the crew's shoot dates — everyone you hire follows them.",
  travel_out: "Is the crew travelling out? Usually the day after the shoot.",
  wrap: "A wrap day — packing up, shipping merchandise, returning props? Usually just the stylists: choose No wrap day and give it to them on their own rows.",
  travel: "Is the crew travelling in? Usually the day before.",
  prep: "Any prep or scout days for the crew?",
};

type Step = "details" | "dates" | "hire" | "ready";

// The name cell's small actions sit closer than a button's own padding, so
// Remove and Download share a line in a 128px column.
const ROW_ACTION = { paddingLeft: "0.375rem", paddingRight: "0.375rem" };

// One step at a time, in the order a job actually gets set up: who it's for
// (it goes on every deal memo), the crew's dates (everyone hired follows
// them), then the people. Only the shoot needs real dates — the other day
// types can be answered with "none", since a local job has no travel.
function stepFor(job: Job, hires: Hire[], skippedDetails: boolean): Step {
  const detailsMissing = !job.client_name || !job.production_company || !job.payroll_provider;
  if (detailsMissing && !skippedDetails) return "details";
  if (nextCrewType(job.crew_dates)) return "dates";
  return hires.length === 0 ? "hire" : "ready";
}

function Blocks({ spans }: { spans: Span[] }) {
  if (!spans.length) return null;
  return (
    <span className="grid gap-px">
      {spans.map(([a, b], i) => {
        const days = spanDays(a, b);
        // Date on one line, the day count under it — the mockup's shape, and
        // it keeps a column narrow enough that "Sun, Oct 4" never breaks.
        return (
          <span key={i} className="grid">
            <DateText>{displaySpan(a, b)}</DateText>
            {days > 1 && <DateText muted>{days} days</DateText>}
          </span>
        );
      })}
    </span>
  );
}

export default function PreProductionPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  // The job's days' dates — what the crew calendar opens on and suggests from
  // before any crew date is set.
  const [dayDates, setDayDates] = useState<string[]>([]);
  const [hires, setHires] = useState<Hire[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [openCell, setOpenCell] = useState<{ who: "crew" | string; type: DayType } | null>(null);
  // Whose Rate popover is open. One popover at a time: opening either kind
  // closes the other.
  const [rateOpen, setRateOpen] = useState<string | null>(null);
  // Released holds are hidden unless asked for; the slot being filled, if any.
  const [showReleased, setShowReleased] = useState(false);
  const [fillingSlot, setFillingSlot] = useState<RoleSlot | null>(null);
  const [newRole, setNewRole] = useState("");
  const [addingTalent, setAddingTalent] = useState(false);
  // Conflict marks come straight from the API (hire.conflicts) and stay: the
  // rule behind them only flags what's never legitimate (services/job_dates.
  // find_conflicts). What a move of the crew's shoot left behind is offered
  // at the move instead: the crew's own travel/prep/wrap if they didn't come
  // along, and everyone with their own dates. Each part goes once it's done.
  const [moveOffer, setMoveOffer] = useState<{ days: number; crewOthers: boolean; hireIds: string[] } | null>(null);
  // Whose dates note is open for writing (it's shown anyway once it has text).
  const [noteOpen, setNoteOpen] = useState<string | null>(null);
  const [addingHire, setAddingHire] = useState(false);
  // The hire form opens by itself when nobody's hired yet (the next step);
  // "Done" closes it anyway, and it stays closed.
  const [hireDismissed, setHireDismissed] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  // The job details card stays up while you're in it, even once the last field
  // is filled — it would otherwise vanish under the cursor mid-edit.
  const [detailsFocused, setDetailsFocused] = useState(false);
  const [skippedDetails, setSkippedDetails] = useState(false);
  // The most recent other job with any job details, for "Same as last job".
  const [lastJob, setLastJob] = useState<{ name: string; client_name: string | null; production_company: string | null; payroll_provider: string | null; per_diem_line: string | null } | null>(null);
  const crewCellRefs = useRef<Partial<Record<DayType, HTMLButtonElement | null>>>({});
  const [removing, setRemoving] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);
  const { show: showToast, node: toastNode } = useToast();
  const [downloadingAll, setDownloadingAll] = useState(false);
  // Whose memos the header button downloads. Empty = everyone. The producer edits one
  // memo and wants just that one back, not the whole zip again.
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Date edits show on screen the moment they're picked and save behind it
  // (see persist). saveSeq is how a slow response, or a refetch started
  // before a newer edit, knows it's out of date and leaves the screen alone.
  const saveSeq = useRef(0);
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());

  const load = useCallback(() => {
    setLoadError(false);
    const seq = saveSeq.current;
    Promise.all([
      api.get<{ job: Job; days: { shoot_date: string | null }[] }>(`/api/jobs/${id}`),
      api.get<Hire[]>(`/api/jobs/${id}/hires`),
    ]).then(([{ job, days }, hires]) => {
      if (seq !== saveSeq.current) return;
      setJob(job);
      setDayDates(days.map((d) => d.shoot_date).filter((d): d is string => !!d));
      setHires(hires);
    })
      .catch(() => setLoadError(true));
  }, [id]);

  useEffect(load, [load]);

  useEffect(() => {
    try { setSkippedDetails(sessionStorage.getItem(`skip-details:${id}`) === "1"); } catch { /* private mode */ }
    api.get<{ id: string; name: string; client_name: string | null; production_company: string | null; payroll_provider: string | null; per_diem_line: string | null }[]>("/api/jobs")
      .then((jobs) => setLastJob(jobs.find((j) => j.id !== id && (j.client_name || j.production_company || j.payroll_provider)) ?? null))
      .catch(() => {});
  }, [id]);

  // Separate calls, not a loop or a helper — useAutosaveField is a real
  // hook and has to be called the same fixed number of times on every render.
  // Each save also updates the page's own copy of the job, which is what
  // decides whether the details are complete and the next step moves on.
  const saveDetail = (field: "client_name" | "production_company" | "payroll_provider" | "location_line" | "per_diem_paid_by") => (v: string) =>
    api.put(`/api/jobs/${id}`, { [field]: v }).then(() => setJob((j) => (j ? { ...j, [field]: v.trim() || null } : j)));
  // Amounts: the field only ever holds digits and a point (cleanAmount), so
  // this always parses; empty clears it.
  const saveAmount = (field: "per_diem_shoot" | "per_diem_other") => (v: string) => {
    const n = v === "" ? null : Number(v);
    return api.put(`/api/jobs/${id}`, { [field]: n }).then(() => setJob((j) => (j ? { ...j, [field]: n } : j)));
  };
  const clientField = useAutosaveField(job?.client_name ?? "", saveDetail("client_name"));
  const prodField = useAutosaveField(job?.production_company ?? "", saveDetail("production_company"));
  const payrollField = useAutosaveField(job?.payroll_provider ?? "", saveDetail("payroll_provider"));
  const locationField = useAutosaveField(job?.location_line ?? "", saveDetail("location_line"));
  const perDiemShootField = useAutosaveField(num(job?.per_diem_shoot)?.toString() ?? "", saveAmount("per_diem_shoot"));
  const perDiemOtherField = useAutosaveField(num(job?.per_diem_other)?.toString() ?? "", saveAmount("per_diem_other"));
  const perDiemPaidField = useAutosaveField(job?.per_diem_paid_by ?? "", saveDetail("per_diem_paid_by"));

  async function fillFromLastJob() {
    if (!job || !lastJob) return;
    const fill: Partial<Job> = {};
    // Per diem is a company policy, so it comes along too; the location line
    // is this job's own and doesn't.
    for (const f of ["client_name", "production_company", "payroll_provider", "per_diem_line"] as const) {
      if (!job[f] && lastJob[f]) fill[f] = lastJob[f];
    }
    if (!Object.keys(fill).length) return;
    const updated = await api.put<Job>(`/api/jobs/${id}`, fill);
    setJob((j) => (j ? { ...j, ...updated } : j));
    // Filled in one click: fold the card now, rather than leaving it up
    // because focus happens to still be on this button.
    (document.activeElement as HTMLElement | null)?.blur();
    setDetailsFocused(false);
  }

  function skipDetails() {
    setSkippedDetails(true);
    try { sessionStorage.setItem(`skip-details:${id}`, "1"); } catch { /* private mode */ }
  }

  function openPopover(who: "crew" | string, type: DayType, el: HTMLButtonElement) {
    anchorRef.current = el;
    setRateOpen(null);
    setOpenCell((cur) => (cur?.who === who && cur.type === type ? null : { who, type }));
  }

  // Saves run one at a time, in the order they were made — setup opens the
  // next date as soon as one is picked, so two can easily be in flight, and
  // the second must not land first. Only the newest save's answer (and the
  // refetch after it, for conflicts and anything else the server works out)
  // is shown; a failure refetches the truth and says so.
  function persist<T>(request: () => Promise<T>, onSaved?: (r: T) => void) {
    const seq = ++saveSeq.current;
    saveChain.current = saveChain.current.then(request).then(
      (r) => {
        if (seq !== saveSeq.current) return;
        onSaved?.(r);
        load();
      },
      (err) => {
        showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that change.");
        load();
      },
    );
  }

  function saveCrewDates(next: DatesByType) {
    if (!job) return;
    const before = job.crew_dates;
    // Travel, prep or wrap the crew has that stayed put while the shoot moved
    // — the shoot is what the server measures a move by (crew_shift_days).
    const othersStayed = DAY_TYPES.some((t) => t !== "shoot" && (next[t] ?? []).length > 0
      && sameSpans(next[t] ?? [], before[t] ?? []));
    const customIds = (hires ?? []).filter((h) => h.custom).map((h) => h.id);
    setJob({ ...job, crew_dates: next });
    setHires((hs) => hs && hs.map((h) => ({ ...h, effective_dates: effectiveDates(baseDates(next, h.kind), h.dates_override) })));
    persist(
      () => api.put<{ job: Job; shift_days: number; conflicts: Record<string, HireConflict[]> }>(`/api/jobs/${id}/crew-dates`, { crew_dates: next }),
      (r) => {
        setJob(r.job);
        if (r.shift_days && (othersStayed || customIds.length)) {
          setMoveOffer({ days: r.shift_days, crewOthers: othersStayed, hireIds: customIds });
        }
        // The job header's date span reads the crew dates too; it lives in the
        // layout, so tell it rather than leave it showing the old span.
        window.dispatchEvent(new Event("job:changed"));
      },
    );
  }

  function saveHireOverride(hire: Hire, next: DatesByType) {
    if (!job) return;
    setOpenCell(null);
    setHires((hs) => hs && hs.map((h) => (h.id === hire.id
      ? { ...h, dates_override: next, custom: isCustom(next), effective_dates: effectiveDates(baseDates(job.crew_dates, h.kind), next) }
      : h)));
    persist(() => api.put(`/api/jobs/${id}/hires/${hire.id}`, { dates_override: next }));
  }

  function openRate(hire: Hire, el: HTMLButtonElement) {
    anchorRef.current = el;
    setOpenCell(null);
    setRateOpen((cur) => (cur === hire.id ? null : hire.id));
  }

  // Not persist(): the popover waits for the answer, so a refused amount
  // stays on screen to fix rather than vanishing into a toast.
  async function saveRate(hire: Hire, r: RateSave) {
    try {
      await api.put(`/api/jobs/${id}/hires/${hire.id}`, r);
      setHires((hs) => hs && hs.map((h) => (h.id === hire.id
        ? { ...h, ...r, rate_source: r.rate_source ?? h.rate_source, rate_suggestion: null,
            rate_source_job_name: r.rate_source ? h.rate_suggestion?.rate_source_job_name ?? null : h.rate_source_job_name }
        : h)));
      setRateOpen(null);
      anchorRef.current?.focus();
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save the rate: ${err.message}` : "Couldn't save the rate.");
    }
  }

  // The whole map each time, as the screen holds it; blanks drop out server
  // side. persist() refetches, which brings back the memo lines it changed.
  function saveDayLabel(day: string, value: string) {
    if (!job) return;
    const text = value.trim();
    if (text === (job.day_labels?.[day] ?? "")) return;
    const next = { ...(job.day_labels ?? {}) };
    if (text) next[day] = text; else delete next[day];
    setJob({ ...job, day_labels: next });
    persist(() => api.put(`/api/jobs/${id}/day-labels`, { day_labels: next }));
  }

  function saveDayNote(hire: Hire, day: string, value: string) {
    const text = value.trim();
    if (text === (hire.day_notes?.[day] ?? "")) return;
    const next = { ...(hire.day_notes ?? {}) };
    if (text) next[day] = text; else delete next[day];
    setHires((hs) => hs && hs.map((h) => (h.id === hire.id ? { ...h, day_notes: next } : h)));
    persist(() => api.put(`/api/jobs/${id}/hires/${hire.id}`, { day_notes: next }));
  }

  function saveDatesNote(hire: Hire, value: string) {
    const note = value.trim() || null;
    if (note === (hire.dates_note ?? null)) { if (!note) setNoteOpen(null); return; }
    setHires((hs) => hs && hs.map((h) => (h.id === hire.id ? { ...h, dates_note: note } : h)));
    if (!note && !Object.keys(hire.day_notes ?? {}).length) setNoteOpen(null);
    persist(() => api.put(`/api/jobs/${id}/hires/${hire.id}`, { dates_note: note ?? "" }));
  }

  // While setup is walking the crew's dates, answering one opens the next, so
  // the crew dates are a run of clicks rather than a hunt for the next
  // empty cell. Otherwise (editing a date later) it just closes.
  function advanceFrom(type: DayType, next: DatesByType) {
    const guided = job && hires && stepFor(job, hires, skippedDetails) === "dates" && nextCrewType(job.crew_dates) === type;
    const following = guided ? nextCrewType(next) : null;
    const el = following ? crewCellRefs.current[following] : null;
    if (!following || !el) { setOpenCell(null); return; }
    anchorRef.current = el;
    setOpenCell({ who: "crew", type: following });
  }

  function commitCrewType(type: DayType, first: string, last: string, append: boolean) {
    if (!job) return;
    const current = job.crew_dates[type] ?? [];
    const spans = append ? sortSpans([...current, [first, last]]) : [[first, last] as Span];
    const next = { ...job.crew_dates, [type]: spans };
    saveCrewDates(next);
    advanceFrom(type, next);
  }

  // "No wrap" and the like: an empty list, which setup reads as answered.
  function setCrewNone(type: DayType) {
    if (!job) return;
    const next = { ...job.crew_dates, [type]: [] };
    saveCrewDates(next);
    advanceFrom(type, next);
  }

  function removeCrewType(type: DayType, index: number) {
    if (!job) return;
    const spans = [...(job.crew_dates[type] ?? [])];
    spans.splice(index, 1);
    saveCrewDates({ ...job.crew_dates, [type]: spans });
    setOpenCell(null);
  }

  function commitHireType(hire: Hire, type: DayType, first: string, last: string, append: boolean) {
    if (!job) return;
    // effective_dates[type] is already "their override if they have one for
    // THIS type, else the crew's" — hire.custom only says whether ANY type is
    // overridden, which is the wrong thing to branch a single column on.
    const base = hire.effective_dates[type] ?? [];
    const next = append ? sortSpans([...base, [first, last]]) : [[first, last] as Span];
    const override = { ...hire.dates_override, [type]: next };
    // If this now matches what they'd follow anyway, drop the key ("same as
    // crew" is a missing key, not a matching value). For talent that's the
    // crew minus prep — so a fitting on the crew's prep day is kept as theirs.
    if (sameSpans(next, baseDates(job.crew_dates, hire.kind)[type] ?? [])) delete override[type];
    saveHireOverride(hire, override);
  }

  function removeHireType(hire: Hire, type: DayType, index: number) {
    const current = hire.effective_dates[type] ?? [];
    const next = [...current];
    next.splice(index, 1);
    saveHireOverride(hire, { ...hire.dates_override, [type]: next });
  }

  function resetHireType(hire: Hire, type: DayType) {
    const override = { ...hire.dates_override };
    delete override[type];
    saveHireOverride(hire, override);
  }

  // Hiring also puts them on the days that already exist and fall on their
  // dates (backend _crew_days_up_to_date) — the toast says so, since it
  // changes those days' crew.
  // One talent field at a time, saved as it's left — segment, rate, fee, notes.
  function saveTalent(hire: Hire, body: Partial<Hire>) {
    setHires((hs) => hs && hs.map((h) => (h.id === hire.id ? { ...h, ...body } : h)));
    persist(() => api.put(`/api/jobs/${id}/hires/${hire.id}`, body));
  }

  async function downloadTalentSheet(kind: "xlsx" | "pdf") {
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/talent-sheet/${kind}`);
      triggerDownload(blob, `Talent holds.${kind}`, filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download the talent hold sheet.");
    }
  }

  function setStatus(hire: Hire, choice: StatusChoice) {
    const body = choice === "hold1" ? { status: "hold", hold_rank: 1 } : choice === "hold2" ? { status: "hold", hold_rank: 2 }
      : { status: choice };
    setHires((hs) => hs && hs.map((h) => (h.id === hire.id ? { ...h, ...body } as Hire : h)));
    persist(() => api.put(`/api/jobs/${id}/hires/${hire.id}`, body), () => {
      if (choice === "confirmed") showToast(`${hire.name} confirmed`);
    });
  }

  function saveSlots(slots: RoleSlot[]) {
    if (!job) return;
    setJob({ ...job, role_slots: slots });
    persist(() => api.put(`/api/jobs/${id}/role-slots`, { role_slots: slots }));
  }

  function addRoles(roles: string[]) {
    const have = new Set((job?.role_slots ?? []).map((s) => s.role.toLowerCase()));
    const fresh = roles.map((r) => r.trim()).filter((r) => r && !have.has(r.toLowerCase()));
    if (!fresh.length) return;
    // Ids are assigned server side; the refetch after saving brings them back.
    saveSlots([...(job?.role_slots ?? []), ...fresh.map((role) => ({ id: "", role, state: "open" as const, hire_id: null }))]);
  }

  function handleHired(name: string, addedToDays: number) {
    showToast(addedToDays
      ? `${name} hired and added to ${addedToDays === 1 ? "1 day" : `${addedToDays} days`}`
      : `${name} hired`);
    load();
  }

  // Two steps: the first click asks, the second removes. Removing someone
  // from the job is refused server side while they're on a day's crew, and the
  // refusal names those days, so it's shown on their row.
  async function handleRemoveHire(hire: Hire) {
    if (confirmRemove !== hire.id) { setConfirmRemove(hire.id); setRowError(null); return; }
    setRemoving(hire.id);
    try {
      await api.delete(`/api/jobs/${id}/hires/${hire.id}`);
      showToast(`${hire.name} removed from the job`);
      load();
    } catch (err) {
      setRowError({ id: hire.id, message: err instanceof Error ? err.message : "Couldn't remove them." });
    } finally {
      setRemoving(null);
      setConfirmRemove(null);
    }
  }

  // "Move them too": everyone with their own dates shifts by what the crew
  // just moved. Offered on every crew move, not only when something now
  // conflicts — a date left behind by a small move can look perfectly legal.
  const byDays = (n: number) => `${Math.abs(n)} ${Math.abs(n) === 1 ? "day" : "days"} ${n < 0 ? "earlier" : "later"}`;
  const afterPart = (o: NonNullable<typeof moveOffer>) => (o.crewOthers || o.hireIds.length ? o : null);

  // The crew's travel, prep and wrap, moved by what the shoot just moved.
  function moveCrewOthers() {
    if (!moveOffer || !job) return;
    const d = moveOffer.days;
    const next: DatesByType = {};
    for (const t of DAY_TYPES) {
      const spans = job.crew_dates[t];
      if (spans === undefined) continue;
      next[t] = t === "shoot" ? spans : spans.map(([a, b]) => [addDays(a, d), addDays(b, d)] as Span);
    }
    saveCrewDates(next);
    setMoveOffer((o) => o && afterPart({ ...o, crewOthers: false }));
    showToast(`Moved the crew's other dates ${byDays(d)}`);
  }

  // "Move them too": everyone who had their own dates at the move shifts by
  // the same amount — offered whether or not they now conflict, since a date
  // left behind by a small move can look perfectly legal.
  async function moveHires() {
    if (!moveOffer) return;
    const { days, hireIds } = moveOffer;
    await Promise.all(hireIds.map((hid) => api.post(`/api/jobs/${id}/hires/${hid}/shift`, { days })));
    setMoveOffer((o) => o && afterPart({ ...o, hireIds: [] }));
    const moved = (hires ?? []).filter((h) => hireIds.includes(h.id));
    showToast(`Moved ${moved.length === 1 ? moved[0].name : `${moved.length} people`} ${byDays(days)}`);
    load();
  }

  async function handleDownloadOne(hireId: string, name: string) {
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/deal-memos/${hireId}/pdf`);
      triggerDownload(blob, `Deal Memo - ${name}.pdf`, filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download that deal memo.");
    }
  }

  // Ticked ones only, in the table's order; nothing ticked means everyone.
  // A single tick gets the PDF itself rather than a zip of one.
  async function handleDownloadPicked() {
    const chosen = (hires ?? []).filter((h) => picked.has(h.id));
    if (chosen.length === 1) return handleDownloadOne(chosen[0].id, chosen[0].name);
    setDownloadingAll(true);
    try {
      const query = chosen.map((h) => `hire_id=${encodeURIComponent(h.id)}`).join("&");
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/deal-memos/zip${query ? `?${query}` : ""}`);
      triggerDownload(blob, "Deal Memos.zip", filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download the deal memos.");
    } finally {
      setDownloadingAll(false);
    }
  }

  if (loadError) return <LoadError message="Couldn't load this job." onRetry={load} />;
  if (!job || !hires) return <div className="space-y-4"><TableSkeleton columns={6} rows={4} /></div>;

  const offerHires = moveOffer ? hires.filter((h) => moveOffer.hireIds.includes(h.id)) : [];
  const conflicted = hires.filter((h) => h.conflicts.length > 0);
  const conflictsFor = (hireId: string): HireConflict[] => hires.find((h) => h.id === hireId)?.conflicts ?? [];
  const names = (list: Hire[]) => list.length <= 2
    ? list.map((h) => h.name.split(" ")[0]).join(" and ")
    : `${list.length} people`;
  const customCount = hires.filter((h) => h.custom && h.kind !== "talent").length;
  // Who's booked vs pencilled in. Released people drop out of the table
  // unless asked for; "Download all" and the ready count are booked only.
  // The crew table and its counts are crew; talent have their own section.
  const crewHires = hires.filter((h) => h.kind !== "talent");
  const talentHires = hires.filter((h) => h.kind === "talent" && (showReleased || statusChoice(h) !== "released"));
  const segments = [...new Set(hires.filter((h) => h.kind === "talent").map((h) => h.segment || "Talent"))];
  const booked = crewHires.filter((h) => statusChoice(h) === "confirmed");
  const onHold = crewHires.filter((h) => statusChoice(h).startsWith("hold"));
  const released = hires.filter((h) => statusChoice(h) === "released");
  const shown = showReleased ? crewHires : crewHires.filter((h) => statusChoice(h) !== "released");
  const slots = job.role_slots ?? [];
  const hireName = (hid: string | null) => hires.find((h) => h.id === hid);
  // Who fills a role: its hire, unless they've been released — then the
  // role is open again (backend build_holds says the same).
  const filledBy = (slot: RoleSlot) => {
    const h = hireName(slot.hire_id);
    return h && statusChoice(h) !== "released" ? h : undefined;
  };
  // Counted against who is on the job now, so a removed hire left ticked never counts.
  const pickedCount = hires.filter((h) => picked.has(h.id)).length;

  // ── What to do next ── (stepFor, above)
  const detailsMissing = !job.client_name || !job.production_company || !job.payroll_provider;
  const showDetailsCard = (detailsMissing && !skippedDetails) || detailsFocused;
  const step = stepFor(job, hires, skippedDetails);
  const nextType = step === "dates" ? nextCrewType(job.crew_dates) : null;
  const steps = ["details", "dates", "hire"].filter((s) => s !== "details" || !skippedDetails || !detailsMissing);
  const showHireForm = addingHire || (step === "hire" && !hireDismissed);
  const carryForward = lastJob && (["client_name", "production_company", "payroll_provider"] as const)
    .some((f) => !job[f] && lastJob[f]) ? lastJob : null;

  // One person's dates for one day type: the table's cell button, and the
  // reason underneath when it's in conflict. `tagged` puts the type's name in
  // the button — for the shared Other days column, which has no per-type header.
  const hireDateCell = (hire: Hire, t: DayType, tagged: boolean) => {
    const open = openCell?.who === hire.id && openCell.type === t;
    const conflicted = conflictsFor(hire.id).some((c) => c.type === t);
    // Per COLUMN, not hire.custom (which is "any type at all is
    // overridden") — otherwise setting just their Shoot day
    // marks Travel/Prep/Wrap as "custom" too.
    // Talent follow nobody, so every date they have is their own: shown at
    // full weight, with no "custom" pill (that means "differs from the
    // crew"), and an empty type is simply unset — never "None".
    const talentRow = hire.kind === "talent";
    const columnCustom = !talentRow && t in hire.dates_override;
    const spans = hire.effective_dates[t] ?? [];
    return (
      <>
        <button
          type="button"
          className={`cell-btn${open ? " is-open" : ""}${conflicted ? " has-conflict" : ""}`}
          onClick={(e) => openPopover(hire.id, t, e.currentTarget)}
          aria-label={`${LABELS[t]} for ${hire.name}`}
          style={tagged && !spans.length && !columnCustom ? { minHeight: 0 } : undefined}
        >
          {/* In the shared column an empty type is just its name, faded:
              most people have neither, and "+ Add" twice on every row read
              as something missing. */}
          {tagged && (spans.length || columnCustom
            ? <DayTypeTag type={t} />
            : <span style={{ opacity: 0.5 }}><DayTypeTag type={t} /></span>)}
          {tagged && !spans.length && !columnCustom ? null : talentRow && spans.length ? (
            <Blocks spans={spans} />
          ) : columnCustom ? (
            spans.length ? (
              // Under the dates, not beside: beside made the
              // table ~17px too wide once any appeared.
              <span className="grid justify-items-start gap-1"><Blocks spans={spans} /><span className="custom-pill">custom</span></span>
            ) : (
              <span className="flex items-center gap-1.5">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>None</span>
                <span className="custom-pill">custom</span>
              </span>
            )
          ) : spans.length ? (
            <span className="inherit"><Blocks spans={spans} /></span>
          ) : (
            <span className="empty">—</span>
          )}
        </button>
        {conflicted && (
          <p className="text-xs mt-1" style={{ color: "var(--danger)" }}>
            {conflictsFor(hire.id).find((c) => c.type === t)?.reason}
          </p>
        )}
      </>
    );
  };

  // The crew's working dates, each once, with the types on it — what the
  // "What's on each day" list labels.
  const labelDays = datesIn(LABELLED_TYPES.flatMap((t) => job.crew_dates[t] ?? [])).map((day) => ({
    day, types: LABELLED_TYPES.filter((t) => (job.crew_dates[t] ?? []).some(([a, b]) => day >= a && day <= b)),
  }));

  // One crew date chip on the Job details card.
  const crewChip = (t: DayType) => {
    const spans = job.crew_dates[t] ?? [];
    const open = openCell?.who === "crew" && openCell.type === t;
    return (
      <button
        key={t}
        type="button"
        ref={(el) => { crewCellRefs.current[t] = el; }}
        className={`cell-btn date-chip${open ? " is-open" : ""}${t === nextType && !open ? " is-next" : ""}`}
        onClick={(e) => openPopover("crew", t, e.currentTarget)}
        aria-label={`${LABELS[t]} for the whole crew`}
      >
        <DayTypeTag type={t} />
        {spans.length ? <Blocks spans={spans} />
          // Answered "none" during setup (an empty list), as against
          // never asked: say so, or it looks skipped.
          : t in job.crew_dates && t !== "shoot" ? <span className="text-xs" style={{ color: "var(--text-secondary)" }}>None</span>
            : <span className="empty">+ Set</span>}
      </button>
    );
  };

  return (
    // The positioning context for every date popover on the page: the crew's
    // dates on the Job details card and each person's in the table.
    <div ref={containerRef} style={{ position: "relative" }}>
      {toastNode}

      {/* Next step */}
      <div className="next-step mb-5" role="status">
        <p className="text-sm" style={{ color: "var(--text-primary)" }}>
          {step === "ready" && conflicted.length > 0 ? (
            <><span className="next-step-label">Check</span>
              {names(conflicted)}&apos;s dates need a look — see the red {conflicted.length === 1 ? "mark" : "marks"} below.</>
          ) : step === "ready" ? (
            <><span className="next-step-label">Ready</span>
              Everyone&apos;s hired and dated — {booked.length} deal {booked.length === 1 ? "memo" : "memos"} ready to go{onHold.length ? `, ${onHold.length} on hold` : ""}.</>
          ) : (
            <><span className="next-step-label">Next · {steps.indexOf(step) + 1} of {steps.length}</span>
              {step === "details" && <>Start with the job details below.</>}
              {nextType && ASK[nextType]}
              {step === "hire" && <>Hire your crew. Start typing a name and your Master Roster fills in the rest.</>}
            </>
          )}
        </p>
        <div className="flex items-center gap-2">
          {step === "details" && (
            <button onClick={skipDetails} className="btn btn-ghost btn-sm">Skip for now</button>
          )}
          {nextType && nextType !== "shoot" && (
            <button onClick={() => setCrewNone(nextType)} className="btn btn-ghost btn-sm">{noneLabel(nextType)}</button>
          )}
          {nextType && (
            <button className="btn btn-primary btn-sm"
              onClick={() => { const el = crewCellRefs.current[nextType]; if (el) openPopover("crew", nextType, el); }}>
              {nextType === "shoot" ? "Set shoot dates" : `Set ${LABELS[nextType]}`}
            </button>
          )}
          {step === "ready" && (
            <button onClick={handleDownloadPicked} disabled={downloadingAll} className="btn btn-primary btn-sm">
              {downloadingAll ? "Preparing…" : pickedCount ? `Download selected (${pickedCount})` : "Download all"}
            </button>
          )}
        </div>
      </div>

      {/* Job details: everything about the job itself, who it's for and the
          crew's dates. The ONE place the crew's dates are edited — the Deal
          Memos table below is only people, each showing the crew's dates in
          muted type unless they have their own. The fields are proper inputs
          while any are missing (or being edited), quiet text once they're in. */}
      <section
        className="card p-5 mb-6"
        aria-labelledby="job-details-heading"
        onFocus={() => setDetailsFocused(true)}
        onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDetailsFocused(false); }}
      >
        <div className="flex items-start justify-between gap-3 flex-wrap mb-4">
          <div>
            <h2 id="job-details-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Job details</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              On every deal memo. Saved as you go.
            </p>
          </div>
          {carryForward && (
            <button onClick={fillFromLastJob} className="btn btn-secondary btn-sm" style={{ whiteSpace: "normal", textAlign: "left" }}>
              Same as {carryForward.name}:{" "}
              {[carryForward.client_name, carryForward.production_company, carryForward.payroll_provider].filter(Boolean).join(" · ")}
            </button>
          )}
        </div>
        <div className="grid gap-4 md:grid-cols-3 mb-5">
          {([
            { id: "client", label: "Client", field: clientField, placeholder: "e.g. Northwind", empty: "Add client" },
            { id: "prodco", label: "Production company", field: prodField, placeholder: "e.g. Seaworthy Productions", empty: "Add production co." },
            { id: "payroll", label: "Payroll provider", field: payrollField, placeholder: "e.g. Wrapbooks", empty: "Add payroll provider" },
          ] as const).map(({ id: fid, label, field, placeholder, empty }, i) => (
            <div key={fid}>
              <div className="flex items-center justify-between">
                <label htmlFor={`detail-${fid}`} className="field-label">{label}</label>
                <SaveStatusDot status={field.status} />
              </div>
              <input
                id={`detail-${fid}`}
                value={field.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                placeholder={showDetailsCard ? placeholder : empty}
                className={showDetailsCard ? "field-input" : "field-ghost"}
                // A ghost field's padding would indent its text past the label.
                style={showDetailsCard ? undefined : { marginLeft: "-0.5rem", width: "calc(100% + 0.5rem)" }}
                // Straight into the first empty one: the next keystroke is
                // the answer.
                autoFocus={step === "details" && i === [clientField, prodField, payrollField].findIndex((f) => !f.value)}
              />
            </div>
          ))}
        </div>

        {/* The deal memo's own lines. Optional, so they never hold up the
            Next bar: an empty Location falls back to Day 1's location. */}
        <div className="mb-5">
          <div className="flex items-center justify-between">
            <label htmlFor="detail-location" className="field-label">Location on deal memos</label>
            <SaveStatusDot status={locationField.status} />
          </div>
          <input
            id="detail-location"
            value={locationField.value}
            onChange={(e) => locationField.handleChange(e.target.value)}
            onBlur={locationField.handleBlur}
            placeholder={showDetailsCard ? "e.g. NJ and NY — empty uses Day 1's location" : "Uses Day 1's location"}
            className={showDetailsCard ? "field-input" : "field-ghost"}
            style={showDetailsCard ? undefined : { marginLeft: "-0.5rem", width: "calc(100% + 0.5rem)" }}
          />
        </div>

        {/* Per diem and the down day: the job's side of the deal. Each
            person's own rates are on their row below. */}
        <div className="mb-5">
        <p className="field-label">
          Per diem{" "}
          <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· on every deal memo</span>
        </p>
        <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
          {([
            { id: "pd-shoot", label: "Shoot days", field: perDiemShootField },
            { id: "pd-other", label: "Non-shoot days", field: perDiemOtherField },
          ] as const).map(({ id: fid, label, field }) => (
            <div key={fid}>
              <div className="flex items-center justify-between">
                <label htmlFor={`detail-${fid}`} className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</label>
                <SaveStatusDot status={field.status} />
              </div>
              <div className="flex items-center gap-1">
                <span className="date-text" style={{ color: "var(--text-muted)" }}>$</span>
                <input
                  id={`detail-${fid}`}
                  inputMode="decimal"
                  value={field.value}
                  onChange={(e) => field.handleChange(cleanAmount(e.target.value))}
                  onBlur={field.handleBlur}
                  onFocus={(e) => e.currentTarget.select()}
                  placeholder="—"
                  className={`${showDetailsCard ? "field-input" : "field-ghost"} date-text`}
                  style={{ width: "8ch" }}
                />
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>/day</span>
              </div>
            </div>
          ))}
          <div>
            <div className="flex items-center justify-between">
              <label htmlFor="detail-pd-paid" className="text-xs" style={{ color: "var(--text-muted)" }}>Paid by</label>
              <SaveStatusDot status={perDiemPaidField.status} />
            </div>
            <input
              id="detail-pd-paid"
              value={perDiemPaidField.value}
              onChange={(e) => perDiemPaidField.handleChange(e.target.value)}
              onBlur={perDiemPaidField.handleBlur}
              placeholder={showDetailsCard ? "e.g. Venmo or cash" : "Add how it's paid"}
              className={showDetailsCard ? "field-input" : "field-ghost"}
              style={showDetailsCard ? undefined : { marginLeft: "-0.5rem", width: "calc(100% + 0.5rem)" }}
            />
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>Down day</p>
            <p className="text-sm py-1.5" style={{ color: "var(--text-primary)" }}>½ of shoot day rate</p>
          </div>
        </div>
        {job.per_diem_line && num(job.per_diem_shoot) === null && num(job.per_diem_other) === null && (
          <p className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>
            Deal memos print &ldquo;{job.per_diem_line}&rdquo; until you set the amounts above.
          </p>
        )}
        </div>

        <p className="field-label">
          Crew dates{" "}
          <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· everyone you hire follows these unless they have their own</span>
        </p>
        <div className="grid gap-2 grid-cols-2 md:grid-cols-5">
          {CORE_TYPES.map(crewChip)}
        </div>
        <p className="field-label mt-3">
          Other days{" "}
          <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· only if the job has them: a down day (½ rate) or a hotel check-in with no travel</span>
        </p>
        <div className="grid gap-2 grid-cols-2 md:grid-cols-5">
          {OTHER_TYPES.map(crewChip)}
        </div>
        {labelDays.length > 0 && (
          <>
            <p className="field-label mt-4">
              What&apos;s on each day{" "}
              <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· optional, printed after the date on every deal memo — e.g. Brand A – Studio, NJ</span>
            </p>
            <div className="grid gap-x-4 gap-y-1.5 md:grid-cols-2">
              {labelDays.map(({ day, types }) => (
                <div key={day} className="flex items-center gap-2">
                  <label htmlFor={`label-${day}`} className="flex items-center gap-2 shrink-0" style={{ width: "11rem" }}>
                    <DateText>{displaySpan(day, day)}</DateText>
                    {types.map((t) => <DayTypeTag key={t} type={t} />)}
                  </label>
                  <input
                    id={`label-${day}`}
                    key={job.day_labels?.[day] ?? ""}
                    defaultValue={job.day_labels?.[day] ?? ""}
                    onBlur={(e) => saveDayLabel(day, e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                    placeholder="—"
                    maxLength={200}
                    className="field-ghost"
                  />
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      {moveOffer && (
        <div className="card p-4 mb-4 grid gap-3" style={{ borderColor: "var(--accent)" }} role="status">
          <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
            The shoot moved {byDays(moveOffer.days)}.
          </p>
          {moveOffer.crewOthers && (
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                The crew&apos;s travel, prep and wrap stayed where they were.
              </p>
              <button onClick={moveCrewOthers} className="btn btn-primary btn-sm">Move them too</button>
            </div>
          )}
          {offerHires.length > 0 && (
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                {names(offerHires)} {offerHires.length === 1 ? "has" : "have"} their own dates, which didn&apos;t move.
              </p>
              <button onClick={moveHires} className={`btn btn-sm ${moveOffer.crewOthers ? "btn-secondary" : "btn-primary"}`}>
                Move {offerHires.length === 1 ? offerHires[0].name.split(" ")[0] : "them"} too
              </button>
            </div>
          )}
          <div>
            <button onClick={() => setMoveOffer(null)} className="btn btn-ghost btn-sm">Leave as is</button>
          </div>
        </div>
      )}

      {/* Roles: her placeholder row for every role, needed or not, so nothing
          goes uncovered. Filling one hires someone into it (a hold or booked);
          only real people ever reach the memos, rooming and per diem. */}
      <section className="card p-5 mb-6" aria-labelledby="roles-heading">
        <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
          <div>
            <h2 id="roles-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Roles</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              A checklist so no role is forgotten: fill each, or mark it not needed.
              {slots.length > 0 && <> {slots.filter((s) => s.state === "open" && !filledBy(s)).length} still open.</>}
            </p>
          </div>
          {slots.length === 0 && (
            <button type="button" onClick={() => addRoles(USUAL_ROLES)} className="btn btn-secondary btn-sm">Add the usual roles</button>
          )}
        </div>
        {slots.length > 0 && (
          <div className="grid gap-1.5 md:grid-cols-2 mb-3">
            {slots.map((slot, i) => {
              const filled = filledBy(slot);
              // Someone released from this role: it's open again, and says who left it.
              const left = !filled ? hireName(slot.hire_id) : undefined;
              const notNeeded = slot.state === "not_needed";
              return (
                <div key={slot.id || `new-${i}`} className="flex items-center gap-2 flex-wrap" style={{ opacity: notNeeded ? 0.55 : 1 }}>
                  <span className="text-sm font-medium" style={{ color: "var(--text-primary)", minWidth: "9rem" }}>{slot.role}</span>
                  {filled ? (
                    <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                      {filled.name} · <span style={{ color: statusChoice(filled) === "confirmed" ? "var(--success)" : "var(--accent-text)" }}>{STATUS_LABEL[statusChoice(filled)]}</span>
                    </span>
                  ) : notNeeded ? (
                    <>
                      <span className="text-xs" style={{ color: "var(--text-muted)" }}>Not needed</span>
                      <button type="button" className="btn btn-ghost btn-sm" aria-label={`${slot.role} is needed after all`}
                        onClick={() => saveSlots(slots.map((s) => (s === slot ? { ...s, state: "open" } : s)))}>Needed after all</button>
                    </>
                  ) : (
                    <>
                      {left && <span className="text-xs" style={{ color: "var(--text-muted)" }}>{left.name} released</span>}
                      <button type="button" className="btn btn-secondary btn-sm" disabled={!slot.id}
                        onClick={() => { setFillingSlot(slot); setAddingHire(false); }}
                        aria-label={`Fill the ${slot.role} role`}>Fill</button>
                      <button type="button" className="btn btn-ghost btn-sm" aria-label={`${slot.role} not needed`}
                        onClick={() => saveSlots(slots.map((s) => (s === slot ? { ...s, state: "not_needed" } : s)))}>Not needed</button>
                    </>
                  )}
                  {!filled && (
                    <button type="button" className="btn btn-remove" aria-label={`Remove the ${slot.role} role`}
                      onClick={() => saveSlots(slots.filter((s) => s !== slot))}>Remove</button>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {fillingSlot && (
          <div className="mb-3">
            <HireForm jobId={id} hired={crewHires} slot={{ id: fillingSlot.id, role: fillingSlot.role }}
              onHired={handleHired} onClose={() => setFillingSlot(null)} />
          </div>
        )}
        <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); addRoles([newRole]); setNewRole(""); }}>
          <label htmlFor="new-role" className="sr-only">Add a role</label>
          <input id="new-role" value={newRole} onChange={(e) => setNewRole(e.target.value)} maxLength={80}
            placeholder="Add a role, e.g. Wardrobe Assist" className="field-input" style={{ maxWidth: "18rem" }} />
          <button type="submit" disabled={!newRole.trim()} className="btn btn-ghost btn-sm">Add</button>
        </form>
      </section>

      <div className="flex items-center justify-between gap-4 mb-3 flex-wrap">
        <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Deal Memos</h2>
        {/* Always here, always secondary: once downloading is the step, the
            Next bar carries the primary button, and a page gets one of those. */}
        <button onClick={handleDownloadPicked} disabled={downloadingAll || (pickedCount === 0 && booked.length === 0)}
          className="btn btn-sm btn-secondary">
          {downloadingAll ? "Preparing…" : pickedCount
            ? `Download selected deal memos · ${pickedCount}`
            : `Download all deal memos · ${booked.length}`}
        </button>
      </div>

      {/* Summary */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mb-3 text-sm" style={{ color: "var(--text-secondary)" }}>
        <span><b style={{ color: "var(--text-primary)" }}>{booked.length}</b> confirmed</span>
        {onHold.length > 0 && <span><b style={{ color: "var(--text-primary)" }}>{onHold.length}</b> on hold</span>}
        <span><b style={{ color: "var(--text-primary)" }}>{crewHires.length - customCount}</b> on crew dates</span>
        <span><b style={{ color: "var(--text-primary)" }}>{customCount}</b> with their own dates</span>
        {released.length > 0 && (
          <button type="button" onClick={() => setShowReleased((v) => !v)} className="text-sm" style={{ color: "var(--accent-text)" }}>
            {showReleased ? "Hide" : "Show"} {released.length} released
          </button>
        )}
      </div>

      <div className="data-table-raised">
        <table>
          <thead>
            <tr>
              <th>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={crewHires.length > 0 && pickedCount === crewHires.length}
                    ref={(el) => { if (el) el.indeterminate = pickedCount > 0 && pickedCount < crewHires.length; }}
                    onChange={(e) => setPicked(e.target.checked ? new Set(crewHires.map((h) => h.id)) : new Set())}
                    disabled={crewHires.length === 0}
                    aria-label="Select every deal memo"
                  />
                  Crew
                </label>
              </th>
              {CORE_TYPES.map((t) => <th key={t}><DayTypeTag type={t} /></th>)}
              <th>Other days</th>
              <th>Rate</th>
            </tr>
          </thead>
          <tbody>
            {hires.length === 0 && (
              <tr>
                <td colSpan={CORE_TYPES.length + 3} className="text-sm" style={{ color: "var(--text-muted)" }}>
                  Nobody hired yet. Everyone you hire gets a deal memo here.
                </td>
              </tr>
            )}
            {shown.map((hire) => (
              <Fragment key={hire.id}>
              <tr>
                <td>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={picked.has(hire.id)}
                      onChange={() => setPicked((prev) => {
                        const next = new Set(prev);
                        if (next.has(hire.id)) next.delete(hire.id); else next.add(hire.id);
                        return next;
                      })}
                      aria-label={`Select ${hire.name}'s deal memo`}
                    />
                    <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{hire.name}</span>
                  </label>
                  {hire.role && <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{hire.role}</p>}
                  <select value={statusChoice(hire)} onChange={(e) => setStatus(hire, e.target.value as StatusChoice)}
                    aria-label={`${hire.name}'s status`} className="field-ghost text-xs mt-0.5"
                    style={{ width: "auto", color: statusChoice(hire) === "confirmed" ? "var(--text-secondary)" : "var(--accent-text)" }}>
                    {(Object.keys(STATUS_LABEL) as StatusChoice[]).map((c) => <option key={c} value={c}>{STATUS_LABEL[c]}</option>)}
                  </select>
                  <span className={`roster-chip${hire.roster_id ? " linked" : ""}`}>
                    {hire.roster_id ? "On Master Roster" : "Not on Master Roster"}
                  </span>
                  {rowError?.id === hire.id && (
                    <p className="text-xs mt-1" style={{ color: "var(--danger)" }}>{rowError.message}</p>
                  )}
                  {confirmRemove === hire.id ? (
                    <span className="flex flex-wrap items-center gap-1 mt-1.5">
                      <button onClick={() => handleRemoveHire(hire)} disabled={removing === hire.id} className="btn btn-sm btn-confirm-remove">
                        {removing === hire.id ? "Removing…" : `Remove ${hire.name.split(" ")[0]}?`}
                      </button>
                      <button onClick={() => setConfirmRemove(null)} className="btn btn-ghost btn-sm">Cancel</button>
                    </span>
                  ) : (
                    <div className="mt-1 flex flex-wrap items-center">
                      {/* Pulled left by its own padding so the word lines up
                          with the name above it. */}
                      <button onClick={() => handleRemoveHire(hire)} className="btn btn-remove" style={{ ...ROW_ACTION, marginLeft: "-0.375rem" }}
                        aria-label={`Remove ${hire.name} from the job`}>
                        Remove
                      </button>
                      {/* Here rather than a column of its own: the table ran
                          past the page once Other days joined it. A word, not
                          an icon — the producer missed it when it said only "PDF". */}
                      <button type="button" onClick={() => handleDownloadOne(hire.id, hire.name)} className="btn btn-ghost btn-sm"
                        style={ROW_ACTION} aria-label={`Download ${hire.name}'s deal memo`}>
                        Download
                      </button>
                      {!hire.dates_note && noteOpen !== hire.id && (
                        <button type="button" onClick={() => setNoteOpen(hire.id)} className="btn btn-ghost btn-sm"
                          style={ROW_ACTION} aria-label={`Add notes to ${hire.name}'s deal memo`}>
                          + Notes
                        </button>
                      )}
                    </div>
                  )}
                </td>
                {CORE_TYPES.map((t) => (
                  <td key={t} className="align-top" style={{ padding: "0.375rem" }}>{hireDateCell(hire, t, false)}</td>
                ))}
                {/* Check-in and Down day share one column: most people have
                    neither, and two mostly empty columns pushed the table
                    wider than the page. Each still opens its own calendar. */}
                <td className="align-top" style={{ padding: "0.375rem" }}>
                  <span className="grid gap-1">{OTHER_TYPES.map((t) => <Fragment key={t}>{hireDateCell(hire, t, true)}</Fragment>)}</span>
                </td>
                <td className="align-top" style={{ padding: "0.375rem" }}>
                  <button
                    type="button"
                    className={`cell-btn${rateOpen === hire.id ? " is-open" : ""}`}
                    onClick={(e) => openRate(hire, e.currentTarget)}
                    aria-label={`Rate for ${hire.name}`}
                  >
                    {hasRates(hire) ? (
                      <span className="grid justify-items-start gap-1">
                        <span className="grid">{rateLines(hire).map((l) => <DateText key={l}>{l}</DateText>)}</span>
                        {hire.rate_source && (
                          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                            {hire.rate_source === "job" ? `Last ${job.client_name ?? "client"} job` : "From Roster"}
                          </span>
                        )}
                      </span>
                    ) : hire.rate_suggestion ? (
                      <span className="grid justify-items-start gap-1">
                        <span className="empty">+ Add rate</span>
                        <span className="grid text-xs" style={{ color: "var(--text-muted)" }}>
                          Suggested
                          {rateLines(hire.rate_suggestion).map((l) => <DateText key={l} muted>{l}</DateText>)}
                        </span>
                      </span>
                    ) : (
                      <span className="empty">+ Add rate</span>
                    )}
                  </button>
                </td>
              </tr>
              {(hire.dates_note || noteOpen === hire.id || Object.keys(hire.day_notes ?? {}).length > 0) && (
                <tr className="note-row">
                  <td colSpan={CORE_TYPES.length + 3} style={{ paddingTop: 0 }}>
                    {(hire.person_days ?? []).length > 0 && (
                      <>
                        <p className="field-label">
                          Day notes{" "}
                          <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· {hire.name.split(" ")[0]}&apos;s own, printed after that date on their deal memo</span>
                        </p>
                        <div className="grid gap-x-4 gap-y-1 md:grid-cols-2 mb-3">
                          {(hire.person_days ?? []).map((d) => (
                            <div key={d.date} className="flex items-center gap-2">
                              <label htmlFor={`daynote-${hire.id}-${d.date}`} className="flex items-center gap-2 shrink-0 flex-wrap" style={{ width: "13rem" }}>
                                <DateText>{displaySpan(d.date, d.date)}</DateText>
                                {d.types.map((t) => <DayTypeTag key={t} type={t} />)}
                              </label>
                              <input
                                id={`daynote-${hire.id}-${d.date}`}
                                key={hire.day_notes?.[d.date] ?? ""}
                                defaultValue={hire.day_notes?.[d.date] ?? ""}
                                onBlur={(e) => saveDayNote(hire, d.date, e.target.value)}
                                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                                placeholder="—"
                                maxLength={200}
                                className="field-ghost"
                              />
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                    <label htmlFor={`note-${hire.id}`} className="field-label">
                      Dates note{" "}
                      <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· anything else, printed under {hire.name.split(" ")[0]}&apos;s dates</span>
                    </label>
                    <textarea
                      id={`note-${hire.id}`}
                      key={hire.dates_note ?? ""}
                      defaultValue={hire.dates_note ?? ""}
                      rows={2}
                      onBlur={(e) => saveDatesNote(hire, e.target.value)}
                      className="field-input"
                    />
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {rateOpen && (() => {
        const hire = hires.find((h) => h.id === rateOpen);
        if (!hire) return null;
        return (
          <Popover
            key={`rate:${hire.id}`}
            anchorRef={anchorRef}
            containerRef={containerRef}
            onClose={() => setRateOpen(null)}
            ariaLabel={`Rate for ${hire.name}`}
            width={320}
          >
            <RateEditor
              name={hire.name}
              clientName={job.client_name}
              rates={hire}
              suggestion={hasRates(hire) ? null : hire.rate_suggestion ?? null}
              source={{ kind: hire.rate_source, jobName: hire.rate_source_job_name ?? null }}
              onSave={(r) => saveRate(hire, r)}
              onCancel={() => setRateOpen(null)}
            />
          </Popover>
        );
      })()}

      {openCell && job && (() => {
        const isCrew = openCell.who === "crew";
        const hire = isCrew ? null : hires.find((h) => h.id === openCell.who) ?? null;
        if (!isCrew && !hire) return null;
        const getBlocks = (t: DayType): Span[] =>
          isCrew ? (job.crew_dates[t] ?? []) : (hire!.effective_dates[t] ?? []);
        // Nothing set for this type yet: offer the date that fits it, from the
        // crew dates already set and the job's own days, not today's month.
        const suggested = !(getBlocks(openCell.type)).length
          ? suggestFor(openCell.type, job.crew_dates, dayDates)
          : null;
        return (
          <Popover
            // A fresh popover per cell: setup moves straight from one crew
            // date to the next, and it has to re-anchor under the new cell.
            key={`${openCell.who}:${openCell.type}`}
            anchorRef={anchorRef}
            containerRef={containerRef}
            onClose={() => setOpenCell(null)}
            ariaLabel={`${LABELS[openCell.type]} for ${isCrew ? "the whole crew" : hire!.name}`}
            width={304}
          >
            <RangeCalendar
              dayType={openCell.type}
              getBlocks={getBlocks}
              crewBlocks={isCrew ? undefined : (job.crew_dates[openCell.type] ?? [])}
              initialMonth={(getBlocks(openCell.type)[0]?.[0] ?? job.crew_dates[openCell.type]?.[0]?.[0] ?? suggested ?? dayDates[0] ?? new Date().toISOString().slice(0, 10)).slice(0, 7)}
              suggestedDate={suggested}
              range={RANGE_TYPES.has(openCell.type)}
              who={isCrew ? "Whole crew" : hire!.name}
              isCrewRow={isCrew}
              onCommit={(a, b, append) => (isCrew ? commitCrewType(openCell.type, a, b, append) : commitHireType(hire!, openCell.type, a, b, append))}
              onRemove={(i) => (isCrew ? removeCrewType(openCell.type, i) : removeHireType(hire!, openCell.type, i))}
              onReset={!isCrew && openCell.type in hire!.dates_override ? () => resetHireType(hire!, openCell.type) : undefined}
              onNone={isCrew && openCell.type !== "shoot" ? () => setCrewNone(openCell.type) : undefined}
            />
          </Popover>
        );
      })()}

      {/* Hire */}
      <div className="mt-4">
        {showHireForm ? (
          <HireForm jobId={id} hired={crewHires} onHired={handleHired} onClose={() => { setAddingHire(false); setHireDismissed(true); }} />
        ) : (
          <button onClick={() => { setAddingHire(true); setHireDismissed(false); }} className="btn btn-secondary btn-sm">+ Hire someone on this job</button>
        )}
      </div>

      {/* Talent: hires too, grouped like her talent hold sheet. They get dates,
          rates and holds like crew, and rooms when they travel — never per
          diem or a crew deal memo; each day's talent list fills from here. */}
      <section className="mt-10" aria-labelledby="talent-heading">
        <div className="flex items-center justify-between gap-4 mb-3 flex-wrap">
          <div>
            <h2 id="talent-heading" className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Talent</h2>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Booked through their agency: the rate here is the agency&apos;s day rate, with its fee on top. Talent keep their own dates — they don&apos;t follow the crew&apos;s.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => downloadTalentSheet("xlsx")} disabled={!talentHires.length} className="btn btn-secondary btn-sm">Talent hold sheet</button>
            <button type="button" onClick={() => downloadTalentSheet("pdf")} disabled={!talentHires.length} className="btn btn-ghost btn-sm">PDF</button>
          </div>
        </div>
        {talentHires.length > 0 && (
          <div className="data-table-raised mb-3">
            <table>
              <thead>
                <tr>
                  <th>Talent</th>
                  {TALENT_TYPES.map((t) => <th key={t}><DayTypeTag type={t} /></th>)}
                  <th>Other days</th>
                  <th>Rate + fee</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {segments.map((seg) => {
                  const inSeg = talentHires.filter((h) => (h.segment || "Talent") === seg);
                  if (!inSeg.length) return null;
                  return (
                    <Fragment key={seg}>
                      <tr><td colSpan={TALENT_TYPES.length + 4} className="text-xs font-semibold" style={{ color: "var(--text-secondary)", background: "var(--bg-inset)" }}>{seg}</td></tr>
                      {inSeg.map((h) => (
                        <tr key={h.id}>
                          <td>
                            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{h.name}</p>
                            {(h.talent_info?.agency || h.talent_info?.agent) && (
                              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                                {[h.talent_info?.agency, h.talent_info?.agent].filter(Boolean).join(" · ")}
                              </p>
                            )}
                            {(h.talent_info?.based || h.talent_info?.portfolio_url) && (
                              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                                {h.talent_info?.based}
                                {h.talent_info?.based && h.talent_info?.portfolio_url && " · "}
                                {h.talent_info?.portfolio_url && (
                                  <a href={h.talent_info.portfolio_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent-text)" }}>Portfolio</a>
                                )}
                              </p>
                            )}
                            <select value={statusChoice(h)} onChange={(e) => setStatus(h, e.target.value as StatusChoice)}
                              aria-label={`${h.name}'s status`} className="field-ghost text-xs mt-0.5"
                              style={{ width: "auto", color: statusChoice(h) === "confirmed" ? "var(--text-secondary)" : "var(--accent-text)" }}>
                              {(Object.keys(STATUS_LABEL) as StatusChoice[]).map((c) => <option key={c} value={c}>{STATUS_LABEL[c]}</option>)}
                            </select>
                            <span className="flex items-center gap-1 mt-1">
                              <label htmlFor={`seg-${h.id}`} className="text-xs" style={{ color: "var(--text-muted)" }}>Segment</label>
                              <input id={`seg-${h.id}`} key={h.segment ?? ""} defaultValue={h.segment ?? ""} list="talent-segments" maxLength={80}
                                onBlur={(e) => { const v = e.target.value.trim(); if (v !== (h.segment ?? "")) saveTalent(h, { segment: v || null }); }}
                                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                                placeholder="—" className="field-ghost text-xs" style={{ width: "8rem" }} />
                            </span>
                            <span className="flex flex-wrap items-center mt-1">
                              <button onClick={() => handleRemoveHire(h)} className="btn btn-remove" style={{ ...ROW_ACTION, marginLeft: "-0.375rem" }}
                                aria-label={`Remove ${h.name} from the job`}>
                                {confirmRemove === h.id ? (removing === h.id ? "Removing…" : `Remove ${h.name.split(" ")[0]}?`) : "Remove"}
                              </button>
                            </span>
                          </td>
                          {TALENT_TYPES.map((t) => (
                            <td key={t} className="align-top" style={{ padding: "0.375rem" }}>{hireDateCell(h, t, false)}</td>
                          ))}
                          <td className="align-top" style={{ padding: "0.375rem" }}>
                            <span className="grid gap-1">
                              {/* A fitting and a down day always; a check-in or wrap only
                                  when they have one (dates copied from before talent kept
                                  their own), so nothing that prints is hidden here. */}
                              {[...TALENT_OTHER_TYPES, ...(["checkin", "wrap"] as DayType[]).filter((t) => (h.effective_dates[t] ?? []).length)]
                                .map((t) => <Fragment key={t}>{hireDateCell(h, t, true)}</Fragment>)}
                            </span>
                          </td>
                          <td>
                            <span className="flex items-center gap-1">
                              <span className="date-text" style={{ color: "var(--text-muted)" }}>$</span>
                              <input key={`r${h.rate_shoot ?? ""}`} defaultValue={num(h.rate_shoot)?.toString() ?? ""} inputMode="decimal"
                                onChange={(e) => { e.target.value = cleanAmount(e.target.value); }}
                                onBlur={(e) => { const v = e.target.value === "" ? null : Number(e.target.value); if (v !== num(h.rate_shoot)) saveTalent(h, { rate_shoot: v }); }}
                                onFocus={(e) => e.currentTarget.select()}
                                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                                aria-label={`${h.name}'s day rate`} placeholder="—" className="field-ghost date-text" style={{ width: "6ch" }} />
                              <span className="text-xs" style={{ color: "var(--text-muted)" }}>+</span>
                              <input key={`f${h.agency_fee_pct ?? ""}`} defaultValue={num(h.agency_fee_pct)?.toString() ?? ""} inputMode="decimal"
                                onChange={(e) => { e.target.value = cleanAmount(e.target.value); }}
                                onBlur={(e) => {
                                  const v = e.target.value === "" ? null : Number(e.target.value);
                                  // Never quietly capped: "2020" was once saved as 100%.
                                  if (v !== null && v > 100) { showToast("An agency fee is a percent up to 100, like 20."); e.target.value = num(h.agency_fee_pct)?.toString() ?? ""; return; }
                                  if (v !== num(h.agency_fee_pct)) saveTalent(h, { agency_fee_pct: v });
                                }}
                                onFocus={(e) => e.currentTarget.select()}
                                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                                aria-label={`${h.name}'s agency fee percent`} placeholder="—" className="field-ghost date-text" style={{ width: "4ch" }} />
                              <span className="text-xs" style={{ color: "var(--text-muted)" }}>%</span>
                            </span>
                          </td>
                          <td>
                            <input key={h.notes ?? ""} defaultValue={h.notes ?? ""} maxLength={500}
                              onBlur={(e) => { const v = e.target.value.trim(); if (v !== (h.notes ?? "")) saveTalent(h, { notes: v || null }); }}
                              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                              aria-label={`Notes for ${h.name}`} placeholder="—" className="field-ghost" />
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            <datalist id="talent-segments">{segments.map((s) => <option key={s} value={s} />)}</datalist>
          </div>
        )}
        {addingTalent ? (
          <HireForm jobId={id} kind="talent" segments={segments.filter((s) => s !== "Talent")}
            shootDates={datesIn(job.crew_dates.shoot ?? [])}
            hired={hires.filter((h) => h.kind === "talent")} onHired={handleHired} onClose={() => setAddingTalent(false)} />
        ) : (
          <button onClick={() => setAddingTalent(true)} className="btn btn-secondary btn-sm">+ Hire talent</button>
        )}
      </section>
    </div>
  );
}
