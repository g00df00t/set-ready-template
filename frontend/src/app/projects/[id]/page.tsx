"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { SETUP_STEPS } from "@/lib/setupSteps";
import { hasWrapped } from "@/lib/nextShoot";

interface Project {
  id: string;
  name: string;
  shoot_date: string | null;
}

interface CrewMember {
  id: string;
  name: string;
  call_time: string | null;
  confirmed_at: string | null;
}

interface ScheduleItem {
  id: string;
  start_time: string;
  end_time: string | null;
  description: string;
  sort_order: number;
}

interface CallSheetStatus {
  id: string;
  sent_at: string | null;
}

interface Summary {
  talent_count: number;
  contact_count: number;
}

const STAY_FIELDS = ["hotel_name", "address", "phone", "website_url", "room_block",
  "check_in_time", "check_out_time", "amenities", "notes"];
const MEAL_FIELDS = ["breakfast_start", "breakfast_end", "breakfast_notes",
  "lunch_start", "lunch_end", "lunch_notes"];

/** True when the producer has actually filled something in. A row can exist with
 *  every field blank — saving and clearing leaves one behind — so the presence of
 *  a record is not the same as the step being done. */
function anyFilled(row: Record<string, string | null> | null, fields: string[]): boolean {
  if (!row) return false;
  return fields.some((f) => (row[f] ?? "").trim() !== "");
}

interface Location {
  location_name: string | null;
  address: string | null;
}

interface Weather {
  condition: string;
  high_f: number | null;
  low_f: number | null;
  precipitation_chance: number | null;
  sunrise: string | null;
  sunset: string | null;
}

function fmtTime(t: string): string {
  const parts = t.split(":");
  const h = parseInt(parts[0]);
  const m = parseInt(parts[1]);
  const ampm = h >= 12 ? "PM" : "AM";
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${ampm}`;
}

function mapsUrl(provider: "apple" | "google", address: string) {
  const enc = encodeURIComponent(address);
  return provider === "apple"
    ? `https://maps.apple.com/?q=${enc}`
    : `https://www.google.com/maps/search/?api=1&query=${enc}`;
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [crew, setCrew] = useState<CrewMember[]>([]);
  const [schedule, setSchedule] = useState<ScheduleItem[]>([]);
  const [location, setLocation] = useState<Location | null>(null);
  const [weather, setWeather] = useState<Weather | null>(null);
  const [callSheet, setCallSheet] = useState<CallSheetStatus | null | "none">(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [hasStay, setHasStay] = useState(false);
  const [hasMeals, setHasMeals] = useState(false);
  // Completed steps fold away by default once there are any. Collapsed rather
  // than deleted: the sequence stays reachable when a producer wants to check
  // what they've already done, and nothing disappears out from under the cursor
  // mid-task the way a self-deleting list does.
  const [showDone, setShowDone] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDate, setEditDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(() => {
    setLoadError(false);
    api.get<Project>(`/api/projects/${id}`).then(setProject).catch(() => setLoadError(true));
    api.get<CrewMember[]>(`/api/projects/${id}/crew`).then(setCrew).catch(() => {});
    api.get<ScheduleItem[]>(`/api/projects/${id}/schedule`).then(setSchedule).catch(() => {});
    api.get<Location>(`/api/projects/${id}/location`).then(setLocation).catch(() => {});
    api.get<{ weather: Weather | null }>(`/api/projects/${id}/call-sheet/location-debug`)
      .then((d) => { if (d.weather) setWeather(d.weather); })
      .catch(() => {});
    api.get<CallSheetStatus>(`/api/projects/${id}/call-sheet`)
      .then(setCallSheet).catch(() => setCallSheet("none"));
    api.get<Summary>(`/api/projects/${id}/summary`).then(setSummary).catch(() => {});
    // Both 404 when never set, which is the normal case — a catch to false is the
    // answer, not an error. Named fields rather than "any value present": the
    // response also carries id and project_id, which are always populated.
    api.get<Record<string, string | null>>(`/api/projects/${id}/accommodation`)
      .then((a) => setHasStay(anyFilled(a, STAY_FIELDS)))
      .catch(() => setHasStay(false));
    api.get<Record<string, string | null>>(`/api/projects/${id}/meals`)
      .then((m) => setHasMeals(anyFilled(m, MEAL_FIELDS)))
      .catch(() => setHasMeals(false));
  }, [id]);

  useEffect(() => { load(); }, [load]);

  function startEdit() {
    if (!project) return;
    setEditName(project.name);
    setEditDate(project.shoot_date ?? "");
    setEditing(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await api.put<Project>(`/api/projects/${id}`, {
        name: editName,
        shoot_date: editDate || null,
      });
      setProject(updated);
      setEditing(false);
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  }

  const sheetSent = callSheet && callSheet !== "none" && !!callSheet.sent_at;
  const sheetGenerated = callSheet && callSheet !== "none";

  /* Whether each setup step is done. The ORDER lives in lib/setupSteps.ts and is
   * shared with the sidebar-foot "Next" prompt — this page only supplies the
   * done-ness, so the two can never disagree about the sequence again.
   *
   * "Send call sheet to crew" is appended rather than living in SETUP_STEPS,
   * because it is a second task on a page already in the sequence, not a
   * destination of its own. */
  const DONE: Record<string, boolean> = {
    "/crew":           crew.length > 0,
    "/talent":         !!(summary && summary.talent_count > 0),
    "/contacts":       !!(summary && summary.contact_count > 0),
    "/location":       !!location?.address,
    "/accommodations": hasStay,
    "/meals":          hasMeals,
    "/schedule":       schedule.length > 0,
    "/call-sheet":     !!sheetGenerated,
  };
  const STEPS: { label: string; href: string; done: boolean; optional?: boolean }[] = [
    ...SETUP_STEPS.map((step) => ({
      label: step.task,
      href: `/projects/${id}${step.path}`,
      done: DONE[step.path] ?? false,
      optional: step.optional,
    })),
    { label: "Send call sheet to crew", href: `/projects/${id}/call-sheet`, done: !!sheetSent },
  ];
  const doneSteps = STEPS.filter((s) => s.done);
  const required = STEPS.filter((s) => !s.optional);
  const requiredDone = required.filter((s) => s.done).length;
  const setupComplete = requiredDone === required.length;

  const crewWithCallTime = crew.filter((m) => m.call_time);
  const firstCall = crewWithCallTime.length > 0
    ? crewWithCallTime.reduce((a, b) => (a.call_time! < b.call_time! ? a : b)).call_time!
    : null;

  const scheduleWithEnd = schedule.filter((s) => s.end_time);
  const wrapTime = scheduleWithEnd.length > 0
    ? scheduleWithEnd.reduce((a, b) => (a.end_time! > b.end_time! ? a : b)).end_time!
    : null;

  const confirmed = crew.filter((m) => m.confirmed_at).length;
  const confirmPct = crew.length > 0 ? (confirmed / crew.length) * 100 : 0;

  if (loadError && !project) return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10">
      <LoadError message="Couldn't load this project." onRetry={load} />
    </div>
  );

  if (!project) return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10 space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <Skeleton width="60%" height="2rem" />
        <Skeleton width="40%" height="1rem" />
      </div>
      {/* Stat row */}
      <div className="grid grid-cols-3 gap-3">
        {[0,1,2].map((i) => (
          <div key={i} className="card px-4 py-4 space-y-2">
            <Skeleton width="50%" height="0.65rem" />
            <Skeleton width="70%" height="1.5rem" />
          </div>
        ))}
      </div>
      {/* Cards */}
      {[0,1].map((i) => (
        <div key={i} className="card px-5 py-4 space-y-2">
          <Skeleton width="30%" height="0.65rem" />
          <Skeleton width="55%" height="1rem" />
          <Skeleton width="80%" height="1rem" />
        </div>
      ))}
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10 space-y-6">

      {/* Project header */}
      {editing ? (
        <div className="card p-5 space-y-4">
          <div>
            <label className="field-label">Project name</label>
            <input aria-label="Project name" value={editName} onChange={(e) => setEditName(e.target.value)} className="field-input" />
          </div>
          <div>
            <label className="field-label">Shoot date</label>
            <DateInput ariaLabel="Shoot date" value={editDate} onChange={setEditDate} min="2000-01-01" max="2100-12-31" />
          </div>
          <div className="flex gap-3">
            <button onClick={handleSave} disabled={saving} className="btn btn-primary btn-sm">
              {saving ? "Saving…" : "Save"}
            </button>
            <button onClick={() => setEditing(false)} className="btn btn-ghost btn-sm">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{project.name}</h2>
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
              {project.shoot_date
                ? new Date(project.shoot_date + "T00:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })
                : "No shoot date set"}
            </p>
          </div>
          <button onClick={startEdit} className="btn btn-ghost btn-sm">Edit</button>
        </div>
      )}


      {/* Once the day is over, the page's job changes: nothing here is going to
          be edited again, so the first thing offered is the record of what
          happened rather than another step to complete. */}
      {hasWrapped(project) && (
        <Link
          href={`/projects/${project.id}/wrap`}
          className="card px-5 py-4 flex items-center justify-between gap-4 transition-opacity hover:opacity-80"
          style={{ textDecoration: "none", borderColor: "var(--accent)" }}
        >
          <span className="min-w-0">
            <span className="block text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              This shoot has wrapped
            </span>
            <span className="block text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              See the wrap report — the day, the crew, who confirmed, and where everything was.
            </span>
          </span>
          <span className="text-sm shrink-0" style={{ color: "var(--text-muted)" }}>→</span>
        </Link>
      )}

      {/* Setup checklist.
       *
       * Finished steps collapse behind a count instead of being deleted. A list
       * that removes rows as you complete them reflows under you and never says
       * where you are in the sequence; one that keeps all nine rows visible pushes
       * the actual snapshot — call times, location, schedule — below the fold on
       * the page you open to see it. Folding splits the difference: early on,
       * with nothing done, the whole path shows, which is what a first-time
       * producer needs. Later it compresses to what is left.
       *
       * The whole block still disappears once the required steps are done, so a
       * set-up project's overview is a snapshot and not a to-do list. Skipped
       * optional steps go with it. */}
      {!setupComplete && callSheet !== null && (
        <div className="card divide-y overflow-hidden" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center justify-between px-5 py-3">
            <span className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
              Set up this project
            </span>
            <span className="text-xs tabular-nums" style={{ color: "var(--text-muted)" }}>
              {requiredDone} of {required.length}
            </span>
          </div>
          {doneSteps.length > 0 && (
            <button
              type="button"
              onClick={() => setShowDone((v) => !v)}
              aria-expanded={showDone}
              className="w-full flex items-center justify-between gap-3 px-5 py-2.5 text-left transition-opacity hover:opacity-75"
            >
              <span className="flex items-center gap-2.5">
                <span aria-hidden="true" className="text-sm shrink-0" style={{ color: "var(--success)" }}>✓</span>
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                  {doneSteps.length} done
                </span>
              </span>
              <span className="text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
                {showDone ? "Hide" : "Show"}
              </span>
            </button>
          )}
          {(showDone ? STEPS : STEPS.filter((s) => !s.done)).map((step) => (
            <Link
              key={step.href + step.label}
              href={step.href}
              className="flex items-center justify-between gap-3 px-5 py-3.5 transition-opacity hover:opacity-75"
              style={{ opacity: step.done ? 0.5 : 1 }}
            >
              <span className="flex items-center gap-2.5 min-w-0">
                <span
                  aria-hidden="true"
                  className="text-sm shrink-0"
                  style={{ color: step.done ? "var(--success)" : "var(--text-muted)" }}
                >
                  {step.done ? "✓" : "○"}
                </span>
                <span className="text-sm truncate" style={{ color: "var(--text-primary)" }}>
                  {step.label}
                </span>
                <span className="sr-only">{step.done ? " — done" : ""}</span>
              </span>
              <span className="flex items-center gap-2.5 shrink-0">
                {step.optional && !step.done && (
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>Optional</span>
                )}
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>→</span>
              </span>
            </Link>
          ))}
        </div>
      )}


      {/* Stat row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="card px-4 py-4">
          <p className="text-xs font-medium uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>First Call</p>
          <p className="text-xl font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
            {firstCall ? fmtTime(firstCall) : "—"}
          </p>
        </div>
        <div className="card px-4 py-4">
          <p className="text-xs font-medium uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>Est. Wrap</p>
          <p className="text-xl font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
            {wrapTime ? fmtTime(wrapTime) : "—"}
          </p>
        </div>
        <div className="card px-4 py-4">
          <p className="text-xs font-medium uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>Confirmed</p>
          <p className="text-xl font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
            {crew.length > 0 ? `${confirmed}/${crew.length}` : "—"}
          </p>
          {crew.length > 0 && (
            <div className="mt-2 h-1 rounded-full overflow-hidden" style={{ background: "var(--bg-elevated)" }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${confirmPct}%`, background: confirmPct === 100 ? "var(--success)" : "var(--accent)" }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Location and Weather sit side by side — both are short glanceable cards,
          and stacking them full width left most of each one empty once the page
          widened. Only paired when both exist: a lone card keeps the full width
          rather than sitting in half of a two-column grid with a hole beside it. */}
      {(location?.address || weather) && (
      <div className={`grid gap-6 ${location?.address && weather ? "md:grid-cols-2" : ""}`}>
      {location?.address && (
        <div className="card px-5 py-4">
          <p className="text-xs font-medium uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>Location</p>
          {location.location_name && (
            <p className="text-sm font-semibold mb-0.5" style={{ color: "var(--text-primary)" }}>{location.location_name}</p>
          )}
          <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>{location.address}</p>
          <div className="flex gap-2">
            <a
              href={mapsUrl("apple", location.address)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs px-2.5 py-1 rounded"
              style={{ border: "1px solid var(--border)", color: "var(--text-secondary)", textDecoration: "none" }}
            >
              📍 Apple Maps
            </a>
            <a
              href={mapsUrl("google", location.address)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs px-2.5 py-1 rounded"
              style={{ border: "1px solid var(--border)", color: "var(--text-secondary)", textDecoration: "none" }}
            >
              🗺 Google Maps
            </a>
          </div>
        </div>
      )}

      {weather && (
        <div className="card px-5 py-4">
          <p className="text-xs font-medium uppercase tracking-wide mb-3" style={{ color: "var(--text-muted)" }}>Weather</p>
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{weather.condition}</p>
              <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>
                {weather.high_f != null && weather.low_f != null && `High ${weather.high_f}° · Low ${weather.low_f}°`}
                {weather.precipitation_chance != null && weather.precipitation_chance > 0 && (
                  <span style={{ color: "var(--text-muted)" }}> · 💧 {weather.precipitation_chance}%</span>
                )}
              </p>
            </div>
            {(weather.sunrise || weather.sunset) && (
              <div className="text-right text-xs" style={{ color: "var(--text-secondary)" }}>
                {weather.sunrise && <p>🌅 {weather.sunrise}</p>}
                {weather.sunset && <p className="mt-1">🌇 {weather.sunset}</p>}
              </div>
            )}
          </div>
        </div>
      )}

      </div>
      )}

      {/* Schedule snapshot */}
      {schedule.length > 0 && (
        <div className="card overflow-hidden">
          <p className="text-xs font-medium uppercase tracking-wide px-5 py-3" style={{ color: "var(--text-muted)", borderBottom: "1px solid var(--border)" }}>
            Schedule
          </p>
          <div className="divide-y" style={{ borderColor: "var(--border)" }}>
            {schedule.map((item) => (
              <div key={item.id} className="flex items-baseline gap-4 px-5 py-3">
                <span className="text-xs tabular-nums shrink-0 w-20" style={{ color: "var(--text-muted)" }}>
                  {fmtTime(item.start_time)}
                  {item.end_time && ` – ${fmtTime(item.end_time)}`}
                </span>
                <span className="text-sm" style={{ color: "var(--text-primary)" }}>{item.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
