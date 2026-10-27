"use client";

// The job's Shoot days (docs/job-layer-plan.md §7). Every date in the crew's
// shoot dates is a day of the shoot: set-up days are cards that open the
// day workspace, and the rest are dashed placeholders until someone sets them
// up — by copying chosen parts of another day (same studio) or starting blank
// (new location). Either way the new day's crew is the people whose dates
// include it (backend _crew_for_day). Nothing is created until asked, so
// moving the crew's dates just moves the placeholders.
//
// "Day N" comes from planDays() in lib/jobDates.ts, which the day sidebar
// reads too.

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { CardListSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { useToast } from "@/components/Toast";
import { fmt as fmtTime } from "@/lib/time";
import { LABELS, displaySpan, offDatesLabel, planDays, toIso, typeOn, type DatesByType, type DayType, type PlannedDay } from "@/lib/jobDates";

interface DaySummary {
  id: string;
  name: string;
  shoot_date: string | null;
  general_call_time: string | null;
  crew_count: number;
  confirmed_count: number;
  call_sheet_sent: boolean;
  /** On this day's crew but not working it by their own dates — hires are
   *  only ever added to days automatically, never taken off. */
  off_dates_crew?: number;
  off_dates_names?: string[];
}
interface Job { id: string; name: string; crew_dates: DatesByType }

type Part = "crew" | "location" | "talent" | "contacts" | "meals" | "hotel" | "schedule" | "notes";

// What a copy can bring, and what's ticked to start with: everything a day in
// the same place shares. Schedule and notes change day to day.
const PARTS: { part: Exclude<Part, "crew">; label: string; on: boolean }[] = [
  { part: "location", label: "Location, parking and company moves", on: true },
  { part: "talent", label: "Talent", on: true },
  { part: "contacts", label: "Agency and client contacts", on: true },
  { part: "meals", label: "Meals", on: true },
  { part: "hotel", label: "Hotel", on: true },
  { part: "schedule", label: "Schedule", on: false },
  { part: "notes", label: "Notes", on: false },
];

const day = (iso: string) => displaySpan(iso, iso);

function offNames(d: DaySummary): string {
  const n = d.off_dates_names ?? [];
  if (!n.length) return `${d.off_dates_crew} ${d.off_dates_crew === 1 ? "person" : "people"}`;
  return n.length <= 2 ? n.join(" and ") : `${n.slice(0, 2).join(", ")} and ${n.length - 2} more`;
}

function entryLabel(e: PlannedDay<DaySummary>): string {
  if (e.number) return `Day ${e.number}`;
  if (e.dayType) return LABELS[e.dayType];
  return e.outside ? offDatesLabel(e.where) : "No date yet";
}

export default function ShootDaysPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [days, setDays] = useState<DaySummary[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  // Which set-up panel is open: a placeholder's date, "extra" for "+ Add a
  // day", or none.
  const [setupFor, setSetupFor] = useState<string | null>(null);
  const [moving, setMoving] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<{ job: Job; days: DaySummary[] }>(`/api/jobs/${id}`)
      .then((r) => { setJob(r.job); setDays(r.days); })
      .catch(() => setLoadError(true));
  }, [id]);

  useEffect(load, [load]);

  async function moveDay(d: DaySummary, to: string) {
    setMoving(d.id);
    try {
      await api.put(`/api/projects/${d.id}`, { shoot_date: to });
      showToast(`Moved to ${day(to)}`);
      load();
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't move it: ${err.message}` : "Couldn't move that day.");
    } finally {
      setMoving(null);
    }
  }

  function done(message: string) {
    setSetupFor(null);
    showToast(message);
    load();
  }

  if (loadError) return <LoadError message="Couldn't load this job's days." onRetry={load} />;
  if (!job || !days) return <CardListSkeleton rows={3} />;

  const plan = planDays(days, job.crew_dates ?? {});
  const placeholders = plan.filter((e) => e.kind === "placeholder");
  const firstPlaceholder = placeholders[0]?.date ?? null;
  const hasShootDates = (job.crew_dates?.shoot ?? []).length > 0;
  const covered = (date: string | null) => !!date && typeOn((t: DayType) => job.crew_dates?.[t] ?? [], date) !== null;
  const sources = plan.filter((e) => e.kind === "day").map((e) => ({
    id: e.day!.id,
    date: e.date,
    label: `${entryLabel(e)}${e.date ? ` · ${day(e.date)}` : ""}`,
  }));
  // Copy from the nearest set-up day before this date — usually the day
  // before, same studio — or the first one there is.
  const sourceFor = (date: string | null) =>
    [...sources].reverse().find((s) => date && s.date && s.date < date)?.id ?? sources[0]?.id ?? null;

  return (
    <div>
      {toastNode}
      <div className="flex items-center justify-between gap-4 mb-6 flex-wrap">
        <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Shoot days</h2>
        {/* Secondary while there are placeholders: setting those up is the
            main thing to do here, and a page gets one primary. */}
        <button type="button" onClick={() => setSetupFor(setupFor === "extra" ? null : "extra")}
          className={`btn ${placeholders.length || days.length ? "btn-secondary" : "btn-primary"}`}>
          + Add a day
        </button>
      </div>

      {setupFor === "extra" && (
        <SetUpDay
          jobId={id}
          title="A day off the schedule"
          subtitle="A scout, a pickup — anything that isn't one of the crew's shoot dates."
          initialDate={null}
          sources={sources}
          defaultSource={sourceFor(null)}
          covered={covered}
          later={[]}
          startBlank
          onCancel={() => setSetupFor(null)}
          onDone={done}
        />
      )}

      {!hasShootDates && (
        <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
          Set the crew&apos;s shoot dates on <Link href={`/jobs/${id}/pre-production`} style={{ color: "var(--accent-text)" }}>Pre-production</Link> and
          every shoot day shows up here, ready to set up.
        </p>
      )}

      {plan.length === 0 ? (
        <div className="card p-8 text-center">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No days yet.</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {plan.map((e) => {
            if (e.kind === "placeholder") {
              const date = e.date!;
              const open = setupFor === date;
              const later = placeholders.filter((p) => p.date! > date);
              return (
                <li key={`p-${date}`}>
                  <div className="card-placeholder flex items-center justify-between gap-4 px-5 py-4">
                    <div>
                      <p className="day-label muted">{entryLabel(e)}</p>
                      <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>
                        <DateText>{day(date)}</DateText>
                        <span style={{ color: "var(--text-muted)" }}> · Not set up yet</span>
                      </p>
                    </div>
                    {!open && (
                      <button type="button" onClick={() => setSetupFor(date)}
                        className={`btn btn-sm ${date === firstPlaceholder ? "btn-primary" : "btn-secondary"}`}>
                        Set up {entryLabel(e)}
                      </button>
                    )}
                  </div>
                  {open && (
                    <SetUpDay
                      jobId={id}
                      title={`Set up ${entryLabel(e)}`}
                      subtitle={day(date)}
                      initialDate={date}
                      sources={sources}
                      defaultSource={sourceFor(date)}
                      covered={covered}
                      later={later.map((p) => ({ date: p.date!, label: entryLabel(p) }))}
                      thisLabel={entryLabel(e)}
                      onCancel={() => setSetupFor(null)}
                      onDone={done}
                    />
                  )}
                </li>
              );
            }
            const d = e.day!;
            // A day that's already happened (or whose sheet went out) is a
            // record: it can sit off the shoot dates without being flagged or
            // offered a move. Testing found a wrapped day with a wrap report and
            // nine confirmations one click from "Move to Tue, Oct 13".
            const settled = d.call_sheet_sent || (!!d.shoot_date && d.shoot_date < toIso(new Date()));
            const flagged = e.outside && !settled;
            return (
              <li key={d.id}>
                {/* The link stretches over the card (its ::after); the Move
                    button sits above that layer, since a button can't go
                    inside a link. */}
                <div className="card-raised relative flex items-center justify-between gap-4 px-5 py-4">
                  <div>
                    <p className={`day-label${flagged ? " warn" : e.number ? "" : " muted"}`}>{entryLabel(e)}</p>
                    <Link href={`/projects/${d.id}`}
                      className="text-sm font-medium after:absolute after:inset-0 after:content-['']"
                      style={{ color: "var(--text-primary)" }}>
                      {d.shoot_date ? <DateText>{day(d.shoot_date)}</DateText> : "No date set"}
                      {d.general_call_time && <span className="font-normal" style={{ color: "var(--text-secondary)" }}> · Call <DateText>{fmtTime(d.general_call_time)}</DateText></span>}
                    </Link>
                    {d.name !== job.name && (
                      <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{d.name}</p>
                    )}
                    {!settled && !!d.off_dates_crew && (
                      <p className="text-xs mt-0.5" style={{ color: "var(--warning)" }}>
                        {/* Named: "1 person" left the producer comparing tables
                            to find out who. Only ever people with a call time
                            or confirmation here — untouched rows follow their
                            dates off the day by themselves. */}
                        {offNames(d)} {d.off_dates_crew === 1 ? "isn't" : "aren't"} working this day by their dates
                      </p>
                    )}
                    {flagged && (
                      <div className="relative z-[1] mt-1.5 flex items-center gap-2 flex-wrap">
                        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                          {firstPlaceholder
                            ? "Not on the crew's shoot dates."
                            // No free shoot date to offer: say what would fix it.
                            : "Not on the crew's shoot dates. Add this date to them on Pre-production, or change the day's date."}
                        </span>
                        {firstPlaceholder && (
                          <button type="button" onClick={() => moveDay(d, firstPlaceholder)} disabled={moving === d.id}
                            className="btn btn-secondary btn-sm">
                            {moving === d.id ? "Moving…" : `Move to ${day(firstPlaceholder)}`}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
                    <span><DateText>{d.confirmed_count}/{d.crew_count}</DateText> confirmed</span>
                    <span className={d.call_sheet_sent ? "badge-confirmed" : "badge-pending"}>
                      {d.call_sheet_sent ? "Sent" : "Not sent"}
                    </span>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Set up a day ─────────────────────────────────────────────────────────────

interface SetUpProps {
  jobId: string;
  title: string;
  subtitle: string;
  /** A placeholder's date (fixed), or null for "+ Add a day" (picked here). */
  initialDate: string | null;
  sources: { id: string; date: string | null; label: string }[];
  defaultSource: string | null;
  covered: (date: string | null) => boolean;
  /** The placeholders after this one, for "Set up Days 2–4 like this". */
  later: { date: string; label: string }[];
  thisLabel?: string;
  /** A day off the schedule is usually somewhere else (a scout), so it starts
   *  on "Start blank"; a placeholder starts on copying the day before. */
  startBlank?: boolean;
  onCancel: () => void;
  onDone: (message: string) => void;
}

function SetUpDay({ jobId, title, subtitle, initialDate, sources, defaultSource, covered, later, thisLabel, startBlank, onCancel, onDone }: SetUpProps) {
  const [mode, setMode] = useState<"copy" | "blank">(defaultSource && !startBlank ? "copy" : "blank");
  const [source, setSource] = useState(defaultSource ?? "");
  const [date, setDate] = useState(initialDate ?? "");
  const [crew, setCrew] = useState(true);
  const [parts, setParts] = useState<Set<Part>>(new Set(PARTS.filter((p) => p.on).map((p) => p.part)));
  const [saving, setSaving] = useState<"one" | "all" | null>(null);
  const [error, setError] = useState("");

  const sourceLabel = sources.find((s) => s.id === source)?.label.split(" · ")[0] ?? "that day";
  const isCovered = covered(date || null);
  // What "crew" will actually mean, so nobody's surprised by who turns up:
  // the dates decide where they reach this day; otherwise it's the source
  // day's crew list (copying) or nobody (blank).
  const crewLabel = isCovered
    ? mode === "copy" ? `Crew working this day, with ${sourceLabel}'s call times` : "Crew working this day (no call times yet)"
    : mode === "copy" ? `${sourceLabel}'s crew, with their call times` : null;

  function toggle(p: Part) {
    setParts((cur) => { const n = new Set(cur); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  }

  async function submit(all: boolean) {
    if (saving) return;
    setSaving(all ? "all" : "one");
    setError("");
    const include: Part[] = [...(crew && crewLabel ? ["crew" as const] : []), ...(mode === "copy" ? [...parts] : [])];
    const dates = [date || null, ...(all ? later.map((l) => l.date) : [])];
    let made = 0;
    try {
      // One at a time, in order: each is its own day, and a failure part way
      // leaves the ones before it set up rather than half of each.
      for (const d of dates) {
        await api.post(`/api/jobs/${jobId}/days`, {
          shoot_date: d,
          ...(mode === "copy" ? { copy_from: source } : { blank: true }),
          include,
        });
        made++;
      }
      onDone(all && later.length ? `${thisLabel}–${later[later.length - 1].label.replace("Day ", "")} set up` : `${thisLabel ?? "Day"} set up`);
    } catch (err) {
      setError(`${made ? `${made} set up, then: ` : ""}${err instanceof Error ? err.message : "couldn't set that up."}`);
      setSaving(null);
    }
  }

  return (
    <div className="card p-5 mt-2 mb-3">
      <div className="mb-4">
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{title}</h3>
        {initialDate ? (
          <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}><DateText>{subtitle}</DateText></p>
        ) : (
          <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{subtitle}</p>
        )}
      </div>

      {!initialDate && (
        <div className="mb-4" style={{ maxWidth: "14rem" }}>
          <label className="field-label" htmlFor="extra-day-date">Date</label>
          <DateInput id="extra-day-date" value={date} onChange={setDate} className="field-input" ariaLabel="Date" />
        </div>
      )}

      <fieldset className="space-y-2 mb-4">
        <legend className="sr-only">Start from</legend>
        {sources.length > 0 && (
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-primary)" }}>
            <input type="radio" name="setup-mode" checked={mode === "copy"} onChange={() => setMode("copy")} />
            Copy from
            <select value={source} onChange={(e) => { setSource(e.target.value); setMode("copy"); }}
              className="field-input" style={{ width: "auto", padding: "0.25rem 0.5rem" }}>
              {sources.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>same place</span>
          </label>
        )}
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-primary)" }}>
          <input type="radio" name="setup-mode" checked={mode === "blank"} onChange={() => setMode("blank")} />
          Start blank
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>a new location</span>
        </label>
      </fieldset>

      <div className="grid gap-1.5 mb-4 sm:grid-cols-2" style={{ paddingLeft: "1.5rem" }}>
        {crewLabel && (
          <label className="flex items-center gap-2 text-sm sm:col-span-2" style={{ color: "var(--text-primary)" }}>
            <input type="checkbox" checked={crew} onChange={() => setCrew((c) => !c)} />
            {crewLabel}
          </label>
        )}
        {mode === "copy" && PARTS.map((p) => (
          <label key={p.part} className="flex items-center gap-2 text-sm" style={{ color: "var(--text-primary)" }}>
            <input type="checkbox" checked={parts.has(p.part)} onChange={() => toggle(p.part)} />
            {p.label}
          </label>
        ))}
      </div>

      {error && <p role="alert" className="text-xs mb-3" style={{ color: "var(--danger)" }}>{error}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => submit(false)} disabled={!!saving || (mode === "copy" && !source)} className="btn btn-primary btn-sm">
          {saving === "one" ? "Setting up…" : `Set up ${thisLabel ?? "this day"}`}
        </button>
        {later.length > 0 && (
          <button type="button" onClick={() => submit(true)} disabled={!!saving || (mode === "copy" && !source)} className="btn btn-secondary btn-sm">
            {saving === "all" ? "Setting up…" : `Set up ${thisLabel}–${later[later.length - 1].label.replace("Day ", "")} like this`}
          </button>
        )}
        <button type="button" onClick={onCancel} className="btn btn-ghost btn-sm">Cancel</button>
      </div>
    </div>
  );
}
