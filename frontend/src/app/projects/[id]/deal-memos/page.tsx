"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { DateInput, DateInputHandle } from "@/components/DateInput";

interface Project {
  id: string;
  client_name: string | null;
  production_company: string | null;
  payroll_provider: string | null;
}

interface CrewMember {
  id: string;
  name: string;
  role: string;
  roster_id: string | null;
  deal_memo_dates: string | null;
}

function triggerDownload(blob: Blob, fallbackName: string, filename: string | null) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename ?? fallbackName;
  link.click();
  URL.revokeObjectURL(url);
}

function ordinal(day: number): string {
  return day % 10 === 1 && day !== 11 ? "st"
    : day % 10 === 2 && day !== 12 ? "nd"
    : day % 10 === 3 && day !== 13 ? "rd" : "th";
}

// "2026-09-29" -> "Sep 29th (Mon)". ISO in because that's what DateInput speaks.
function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  const day = d.getDate();
  const month = d.toLocaleDateString("en-US", { month: "short" });
  const weekday = d.toLocaleDateString("en-US", { weekday: "short" });
  return `${month} ${day}${ordinal(day)} (${weekday})`;
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

// A single day reads "Sep 29th - Mon", matching the producer's own real dates blocks
// exactly. A range collapses to one line instead of one per day — a 4-day
// shoot is "Sep 29th (Mon) – Oct 2nd (Thu)", not four separate lines, which
// is the whole point: fewer lines to read, fewer clicks to make them.
function formatDateOrRange(fromIso: string, toIso: string): string {
  if (fromIso === toIso) {
    const d = new Date(`${fromIso}T00:00:00`);
    const day = d.getDate();
    const month = d.toLocaleDateString("en-US", { month: "short" });
    const weekday = d.toLocaleDateString("en-US", { weekday: "short" });
    return `${month} ${day}${ordinal(day)} - ${weekday}`;
  }
  return `${formatDate(fromIso)} – ${formatDate(toIso)}`;
}

// The producer's own vocabulary for a shoot day's type — the same four labels her
// rooming list and talent hold docs use as column headers (Travel / Scout-Prep
// / Shoot / Wrap-Trvl). Reusing it here means a producer reads the same words
// across every document instead of a new label just for this page.
//
// Type first, then date — picking the category before the date reads more
// naturally than the reverse, and it's also the only way to fit the real
// shape of a shoot: someone can have two separate Shoot day blocks with a
// gap between them (Dana Whitfield's real dates: Oct 11 travels in, Oct 12
// shoot day, Oct 16 shoot day), which a single shared date range can't
// express no matter which order you fill it in. Travel in and out are single
// days almost always; prep/scout, shoot and a stylist's wrap days can span.
// "Wrap day" and "Travel out" were once one "Wrap/Travel out" — a wrap day is
// packing up and returning props, usually the stylists' alone, not leaving.
const SINGLE_DAY_TYPES = ["Travel in", "Travel out"];
const RANGE_DAY_TYPES = ["Prep/Scout", "Shoot day", "Wrap day"];
const DAY_TYPES = ["Travel in", "Prep/Scout", "Shoot day", "Wrap day", "Travel out"];

// Same debounced-autosave shape as the Notes page — one field, one save, no
// form submit. Reused three times here (client/production co./payroll
// provider) plus once per crew row (their Dates block), so it's a hook
// instead of copy-pasted four times. Also exposes saveNow for the date
// quick-add buttons, which shouldn't wait out the debounce to feel instant.
function useAutosaveField(initial: string, save: (value: string) => Promise<void>) {
  const [value, setValue] = useState(initial);
  const [status, setStatus] = useState<"saved" | "unsaved" | "saving" | "">("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialLoad = useRef(true);

  useEffect(() => {
    setValue(initial);
    initialLoad.current = true;
    const t = setTimeout(() => { initialLoad.current = false; }, 0);
    return () => clearTimeout(t);
  }, [initial]);

  async function commit(v: string) {
    setStatus("saving");
    await save(v).catch(console.error);
    setStatus("saved");
    setTimeout(() => setStatus(""), 2000);
  }

  function handleChange(v: string) {
    setValue(v);
    if (initialLoad.current) return;
    setStatus("unsaved");
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => commit(v), 1200);
  }

  function handleBlur() {
    if (status === "unsaved") {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      commit(value);
    }
  }

  function saveNow(v: string) {
    setValue(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    commit(v);
  }

  return { value, status, handleChange, handleBlur, saveNow };
}

function StatusDot({ status }: { status: "saved" | "unsaved" | "saving" | "" }) {
  if (!status) return null;
  const text = status === "unsaved" ? "Unsaved" : status === "saving" ? "Saving…" : "Saved";
  const color = status === "saved" ? "var(--success)" : "var(--text-muted)";
  return <span className="text-xs" style={{ color }}>{text}</span>;
}

function JobDetailField({ label, projectId, field, initial }: {
  label: string; projectId: string; field: string; initial: string;
}) {
  const { value, status, handleChange, handleBlur } = useAutosaveField(
    initial,
    (v) => api.put(`/api/projects/${projectId}`, { [field]: v }),
  );
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</label>
        <StatusDot status={status} />
      </div>
      <input
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onBlur={handleBlur}
        className="field-input"
      />
    </div>
  );
}

// A little narrower than a full text field — this is a date, not a sentence,
// and stretching it edge to edge (the previous version) was most of the
// wasted space Patrick flagged.
const DATE_FIELD_WIDTH = { width: "150px", flex: "0 0 auto" } as const;

function CrewRow({ member, projectId, defaultDate, onDownload }: {
  member: CrewMember; projectId: string; defaultDate: string;
  onDownload: (id: string, name: string) => void;
}) {
  const { value, status, handleChange, handleBlur, saveNow } = useAutosaveField(
    member.deal_memo_dates ?? "",
    (v) => api.put(`/api/projects/${projectId}/crew/${member.id}`, { deal_memo_dates: v }),
  );
  const [downloading, setDownloading] = useState(false);
  const [activeType, setActiveType] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState(defaultDate);
  const [toDate, setToDate] = useState(defaultDate);
  const fromRef = useRef<DateInputHandle>(null);
  const toRef = useRef<DateInputHandle>(null);

  // Picks up where the last entry left off — travel on the 11th suggests the
  // 12th for whatever's added next, not the project's shoot date all over
  // again. Deliberately doesn't guess a span's *length* (e.g. assuming every
  // shoot is 3 days): that varies too much job to job to default confidently,
  // so a range still opens as a single day and stretches only if you drag
  // "to" out yourself — this only saves the "what date do I even start at"
  // step, which is the part that's actually predictable.
  const nextSuggestedDate = useRef(defaultDate);

  function openType(dayType: string) {
    setActiveType(dayType);
    setFromDate(nextSuggestedDate.current);
    setToDate(nextSuggestedDate.current);
  }

  // The field appears already filled with the suggested date, which reads as
  // "here's your answer" rather than "here's a starting point, change it if
  // you want" — nothing about a filled-in field invites a click. Popping the
  // calendar open the moment it appears is what actually shows there's a
  // date to pick, the same way "to" already does once "from" is set. Waits a
  // tick because the field doesn't exist in the DOM until this render commits
  // — activeType is what gates whether it's there at all.
  useEffect(() => {
    if (activeType) requestAnimationFrame(() => fromRef.current?.openPicker());
  }, [activeType]);

  function commitLine(dayType: string, from: string, to: string) {
    if (!from || !to) return;
    const line = `${formatDateOrRange(from, to)} - ${dayType}`;
    const next = value ? `${value}\n${line}` : line;
    saveNow(next);
    setActiveType(null);
    nextSuggestedDate.current = addDays(to, 1);
  }

  // Single-day types commit the instant a date is picked — one click, done.
  // Range types jump straight into the "to" field's own calendar (the
  // Alaska/Delta pattern) rather than committing immediately, since the
  // point of picking a range type is usually to span more than one day.
  function handleFromChange(v: string) {
    setFromDate(v);
    if (activeType && SINGLE_DAY_TYPES.includes(activeType)) {
      commitLine(activeType, v, v);
      return;
    }
    if (!toDate || toDate < v) setToDate(v);
    if (v) requestAnimationFrame(() => toRef.current?.openPicker());
  }

  // Changing "to" is itself the confirmation for a range type — no separate
  // save click needed, matching how the single-day types commit on pick.
  function handleToChange(v: string) {
    setToDate(v);
    if (activeType) commitLine(activeType, fromDate, v);
  }

  async function handleClick() {
    setDownloading(true);
    try {
      await onDownload(member.id, member.name);
    } finally {
      setDownloading(false);
    }
  }

  // Grows with the content instead of clipping it inside a fixed-height box
  // that needs its own internal scroll to read — the whole point was to see
  // the full list without scrolling within a crew member's own card.
  const rowCount = Math.max(3, value ? value.split("\n").length : 0);

  return (
    <div className="py-4 border-b" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-center justify-between gap-4 mb-3">
        <div>
          <span className="font-medium" style={{ color: "var(--text-primary)" }}>{member.name}</span>
          <span className="text-sm ml-2" style={{ color: "var(--text-muted)" }}>{member.role}</span>
          {!member.roster_id && (
            <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>
              — not on the Roster, so rate and agency will be blank
            </span>
          )}
        </div>
        <button onClick={handleClick} disabled={downloading} className="btn btn-ghost btn-sm">
          {downloading ? "Preparing…" : "Download"}
        </button>
      </div>

      <div className="flex items-center justify-between mb-2">
        <label className="text-xs" style={{ color: "var(--text-muted)" }}>Dates</label>
        <StatusDot status={status} />
      </div>

      {/* Buttons on the left, the growing list on the right — using the
          row's full width instead of stacking everything (and then clipping
          it) in a single narrow column. */}
      <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(200px, 260px) 1fr" }}>
        <div className="flex flex-col items-start gap-1">
          {DAY_TYPES.map((dayType) => {
            const isActive = activeType === dayType;
            const isRange = RANGE_DAY_TYPES.includes(dayType);
            return (
              <div key={dayType} className="flex flex-wrap items-center gap-1">
                <button
                  type="button"
                  onClick={() => (isActive ? setActiveType(null) : openType(dayType))}
                  className={isActive ? "btn btn-primary btn-sm" : "btn btn-ghost btn-sm"}
                >
                  + {dayType}
                </button>
                {isActive && (
                  <>
                    <DateInput
                      ref={fromRef}
                      value={fromDate}
                      onChange={handleFromChange}
                      ariaLabel={`${dayType} date for ${member.name}`}
                      style={DATE_FIELD_WIDTH}
                    />
                    {isRange && (
                      <>
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>to</span>
                        <DateInput
                          ref={toRef}
                          value={toDate}
                          onChange={handleToChange}
                          ariaLabel={`${dayType} end date for ${member.name}`}
                          style={DATE_FIELD_WIDTH}
                          min={fromDate || undefined}
                        />
                        <button
                          type="button"
                          onClick={() => commitLine(dayType, fromDate, toDate)}
                          className="btn btn-ghost btn-sm"
                          title="Use this as a single day, without picking a different end date"
                        >
                          Add
                        </button>
                      </>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>

        <textarea
          value={value}
          onChange={(e) => handleChange(e.target.value)}
          onBlur={handleBlur}
          rows={rowCount}
          placeholder={"Pick a day type on the left, then a date, or type directly — e.g.\nAug 24th - Mon - travels in"}
          className="field-input resize-none"
        />
      </div>
    </div>
  );
}

export default function DealMemosPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [shootDate, setShootDate] = useState("");
  const [crew, setCrew] = useState<CrewMember[] | null>(null);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Project & { shoot_date: string | null }>(`/api/projects/${id}`).then((p) => {
      setProject(p);
      setShootDate(p.shoot_date ?? "");

      // Carry forward Client / Production Company / Payroll Provider from the
      // most recent other project that has them, rather than asking a
      // producer to retype her own company's name on every single job. Only
      // fires once — the moment any of the three gets saved (even as a
      // carried-forward default), it's no longer null and this never
      // re-triggers, so an intentionally-cleared field stays cleared.
      if (!p.client_name && !p.production_company && !p.payroll_provider) {
        api.get<(Project & { id: string })[]>("/api/projects").then((all) => {
          const source = all.find((other) =>
            other.id !== id
            && (other.client_name || other.production_company || other.payroll_provider)
          );
          if (!source) return;
          const defaults = {
            client_name: source.client_name,
            production_company: source.production_company,
            payroll_provider: source.payroll_provider,
          };
          api.put(`/api/projects/${id}`, defaults).then(() =>
            setProject((prev) => prev && { ...prev, ...defaults }),
          ).catch(console.error);
        }).catch(console.error);
      }
    }).catch(console.error);
    api.get<CrewMember[]>(`/api/projects/${id}/crew`).then(setCrew).catch(console.error);
  }, [id]);

  async function handleDownloadOne(crewId: string, name: string) {
    setError("");
    try {
      const { blob, filename } = await downloadFile(`/api/projects/${id}/deal-memos/${crewId}/pdf`);
      triggerDownload(blob, `Deal Memo - ${name}.pdf`, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not download the deal memo");
    }
  }

  async function handleDownloadAll() {
    setError("");
    setDownloadingAll(true);
    try {
      const { blob, filename } = await downloadFile(`/api/projects/${id}/deal-memos/zip`);
      triggerDownload(blob, "Deal Memos.zip", filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not download the deal memos");
    } finally {
      setDownloadingAll(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Deal Memos</h2>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            One per crew member, filled in from the Roster — rate, agency and contact info, never
            retyped. Download individually or all at once.
          </p>
        </div>
        <button
          onClick={handleDownloadAll}
          disabled={downloadingAll || !crew?.length}
          className="btn btn-primary btn-sm"
        >
          {downloadingAll ? "Preparing…" : "Download all"}
        </button>
      </div>

      {error && (
        <div className="text-sm mb-4" style={{ color: "var(--danger)" }}>{error}</div>
      )}

      {project && (
        <div
          className="p-4 mb-8 rounded-lg grid grid-cols-1 md:grid-cols-3 gap-4"
          style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
        >
          <JobDetailField label="Client" projectId={id} field="client_name" initial={project.client_name ?? ""} />
          <JobDetailField label="Production company" projectId={id} field="production_company" initial={project.production_company ?? ""} />
          <JobDetailField label="Payroll provider" projectId={id} field="payroll_provider" initial={project.payroll_provider ?? ""} />
        </div>
      )}

      {/* Gated on project too, not just crew — CrewRow seeds its date range
          from defaultDate exactly once, at mount, and project (which carries
          the shoot date) doesn't always resolve before crew does. Mounting
          early would lock every row's initial date in blank. */}
      {crew === null || project === null ? null : crew.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Add crew before generating deal memos.
        </p>
      ) : (
        <div>
          {crew.map((member) => (
            <CrewRow key={member.id} member={member} projectId={id} defaultDate={shootDate} onDownload={handleDownloadOne} />
          ))}
        </div>
      )}
    </div>
  );
}
