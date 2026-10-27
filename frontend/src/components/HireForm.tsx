"use client";

// Hiring someone on a job, starting from the Master Roster.
//
// The point (the producer's ask): a producer shouldn't retype a name, role and email
// the app already knows. Type "Pat" and the roster matches appear, the best
// one already highlighted — Enter takes it, and role, email and phone fill in.
// Focus the empty field and the whole roster lists, which doubles as "pick
// from the Master Roster" without a second button.
//
// It never fills anyone in on its own. Two people can share a first name, and
// "Pat" might be a new Pat — so a match is offered, and the producer takes it.
// Someone new is just typed in full; the backend saves them to the Master
// Roster too (HireCreate.save_to_roster), and the hint says so.

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { DateText } from "@/components/DateText";
import { addDays, displaySpan } from "@/lib/jobDates";

interface RosterEntry {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  department: string | null;
}

interface Props {
  jobId: string;
  /** Who's already hired, so they aren't offered again. */
  hired: { roster_id: string | null; email: string | null }[];
  /** addedToDays: how many existing days they were put on, by their dates. */
  onHired: (name: string, addedToDays: number) => void;
  onClose: () => void;
  /** Filling one of the job's role slots: the role is filled in, and the
   *  form closes once they're hired — a slot takes one person. */
  slot?: { id: string; role: string };
  /** Hiring talent: offers the Roster's talent, and asks for their segment
   *  ("Brand Women") — the talent hold sheet's sections. */
  kind?: "crew" | "talent";
  segments?: string[];
  /** Talent: the crew's shoot dates to pick theirs from. Talent keep their
   *  own schedule — the backend builds it from the days picked
   *  (job_dates.talent_dates): in the day before, out the day after. */
  shootDates?: string[];
}

// How they're hired: booked, or pencilled in as a 1st or 2nd hold
// (backend services/holds.py). A hold stays off the day's crew, the rooming
// list and per diem until it's confirmed.
type HireAs = "confirmed" | "hold1" | "hold2";

const MAX_MATCHES = 8;

export function HireForm({ jobId, hired, onHired, onClose, slot, kind = "crew", segments = [], shootDates = [] }: Props) {
  const talent = kind === "talent";
  const [days, setDays] = useState<string[]>(shootDates);
  const [segment, setSegment] = useState(segments[segments.length - 1] ?? "");
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [name, setName] = useState("");
  const [role, setRole] = useState(slot?.role ?? "");
  const [hireAs, setHireAs] = useState<HireAs>("confirmed");
  const [email, setEmail] = useState("");
  const [picked, setPicked] = useState<RosterEntry | null>(null);
  // Until the Roster has loaded, Enter in the name field would submit what's
  // typed as a brand-new person — and save them to the Master Roster — instead
  // of taking the match that was about to appear. A quick "Dana ⏎ ⏎" made a
  // junk "Dana" that way (2026-09-28).
  const [rosterLoaded, setRosterLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const nameRef = useRef<HTMLInputElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    api.get<RosterEntry[]>(`/api/roster?type=${kind}`).then(setRoster).catch(() => setRoster([]))
      .finally(() => setRosterLoaded(true));
    nameRef.current?.focus();
  }, []);

  const matches = useMemo(() => {
    const hiredRoster = new Set(hired.map((h) => h.roster_id).filter(Boolean));
    const hiredEmail = new Set(hired.map((h) => h.email?.toLowerCase()).filter(Boolean));
    const available = roster.filter((r) => !hiredRoster.has(r.id) && !(r.email && hiredEmail.has(r.email.toLowerCase())));
    const q = name.trim().toLowerCase();
    if (!q) return available.slice(0, MAX_MATCHES);
    // Names that start with what was typed first, then anything that
    // contains it — in the name, the role or the email.
    const starts = available.filter((r) => r.name.toLowerCase().split(/\s+/).some((w) => w.startsWith(q)) || r.name.toLowerCase().startsWith(q));
    const rest = available.filter((r) => !starts.includes(r) &&
      [r.name, r.role, r.email].some((f) => f?.toLowerCase().includes(q)));
    return [...starts, ...rest].slice(0, MAX_MATCHES);
  }, [roster, hired, name]);

  function pick(entry: RosterEntry) {
    setPicked(entry);
    setName(entry.name);
    // Filling a slot keeps the slot's role — that's the job they're held for.
    if (!slot) setRole(entry.role ?? "");
    setEmail(entry.email ?? "");
    setOpen(false);
    // Everything's filled in: the next Enter should hire them.
    requestAnimationFrame(() => addRef.current?.focus());
  }

  function onNameKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !rosterLoaded) { e.preventDefault(); return; }
    if (!open || matches.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); pick(matches[active]); }
    else if (e.key === "Escape") { setOpen(false); }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (saving || !name.trim()) return;
    setSaving(true); setError("");
    try {
      const hired = await api.post<{ added_to_days?: number }>(`/api/jobs/${jobId}/hires`, {
        name: name.trim(),
        role: role.trim() || null,
        email: email.trim() || null,
        roster_id: picked?.id ?? null,
        phone: picked?.phone ?? null,
        department: picked?.department ?? null,
        ...(hireAs === "confirmed" ? {} : { status: "hold", hold_rank: hireAs === "hold1" ? 1 : 2 }),
        ...(slot ? { slot_id: slot.id } : {}),
        ...(talent ? { kind: "talent", segment: segment.trim() || null, shoot_days: days } : {}),
      });
      onHired(name.trim(), hired.added_to_days ?? 0);
      if (slot) { onClose(); return; }
      // Stay open, cleared, for the next person — hiring is usually a run of
      // people, not one.
      setName(""); setRole(""); setEmail(""); setPicked(null); setActive(0);
      nameRef.current?.focus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't hire them.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="card p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative">
          <label className="field-label" htmlFor="hire-name">Name</label>
          <input
            ref={nameRef}
            id="hire-name"
            required
            autoComplete="off"
            role="combobox"
            aria-expanded={open && matches.length > 0}
            aria-controls="hire-matches"
            value={name}
            placeholder="Start typing a name…"
            onChange={(e) => { setName(e.target.value); setPicked(null); setOpen(true); setActive(0); }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={onNameKey}
            className="field-input"
            style={{ width: "16rem" }}
          />
          {open && matches.length > 0 && (
            <ul
              id="hire-matches"
              role="listbox"
              className="popover-surface absolute left-0 z-20 mt-1 py-1 overflow-auto"
              style={{ width: "22rem", maxHeight: "18rem" }}
            >
              {!name.trim() && (
                <li className="px-3 pt-1 pb-1.5 text-[11px] font-semibold tracking-wide uppercase" style={{ color: "var(--text-muted)" }}>
                  Master Roster
                </li>
              )}
              {matches.map((m, i) => (
                <li
                  key={m.id}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => { e.preventDefault(); pick(m); }}
                  onMouseEnter={() => setActive(i)}
                  className="px-3 py-2 cursor-pointer"
                  style={{ background: i === active ? "var(--accent-subtle)" : undefined }}
                >
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{m.name}</p>
                  <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {[m.role, m.email].filter(Boolean).join(" · ") || "No role or email saved"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <label className="field-label" htmlFor="hire-role">Role on this job</label>
          <input id="hire-role" value={role} onChange={(e) => setRole(e.target.value)} className="field-input" style={{ width: "10rem" }} />
        </div>
        {talent && (
          <div>
            <label className="field-label" htmlFor="hire-segment">Segment</label>
            <input id="hire-segment" value={segment} onChange={(e) => setSegment(e.target.value)} list="hire-segments"
              placeholder="e.g. Brand Women" maxLength={80} className="field-input" style={{ width: "10rem" }} />
            <datalist id="hire-segments">{segments.map((s) => <option key={s} value={s} />)}</datalist>
          </div>
        )}
        <div>
          <label className="field-label" htmlFor="hire-email">Email</label>
          <input id="hire-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="field-input" style={{ width: "15rem" }} />
        </div>
        <div>
          <label className="field-label" htmlFor="hire-as">Hire as</label>
          <select id="hire-as" value={hireAs} onChange={(e) => setHireAs(e.target.value as HireAs)} className="field-input" style={{ width: "8.5rem" }}>
            <option value="confirmed">Confirmed</option>
            <option value="hold1">1st hold</option>
            <option value="hold2">2nd hold</option>
          </select>
        </div>
        <button ref={addRef} type="submit" disabled={saving || !name.trim() || (talent && shootDates.length > 0 && !days.length)} className="btn btn-primary btn-sm">
          {saving ? "Hiring…" : hireAs === "confirmed" ? "Hire" : "Hold"}
        </button>
        <button type="button" onClick={onClose} className="btn btn-ghost btn-sm">Done</button>
      </div>
      {talent && shootDates.length > 0 && (
        <div className="mt-3">
          <p className="field-label" id="hire-days-label">Shoot days</p>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-labelledby="hire-days-label">
            {shootDates.map((d) => {
              const on = days.includes(d);
              return (
                <button key={d} type="button" aria-pressed={on}
                  onClick={() => setDays((ds) => (on ? ds.filter((x) => x !== d) : [...ds, d].sort()))}
                  className={`btn btn-sm ${on ? "btn-secondary" : "btn-ghost"}`}>
                  <DateText>{displaySpan(d, d)}</DateText>
                </button>
              );
            })}
          </div>
          <p className="text-xs mt-1.5" style={{ color: "var(--text-secondary)" }}>
            {days.length
              ? <>Travel in <DateText>{displaySpan(addDays(days[0], -1), addDays(days[0], -1))}</DateText>, out{" "}
                  <DateText>{displaySpan(addDays(days[days.length - 1], 1), addDays(days[days.length - 1], 1))}</DateText>
                  {days.length > 1 && addDays(days[0], days.length - 1) !== days[days.length - 1] && <> · they stay between shoot days</>}
                  . Change any of it in the table after.</>
              : <>Pick the days they shoot.</>}
          </p>
        </div>
      )}
      <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
        {picked
          ? <>From your Master Roster. Change the role if they&apos;re doing something different on this job.</>
          : name.trim() && matches.length === 0
            ? <>Not on your Master Roster — they&apos;ll be saved to it when you hire them.</>
            : <>Type a name, or pick from your Master Roster. <kbd>↓</kbd> <kbd>Enter</kbd> works too.</>}
      </p>
      {error && <p role="alert" className="text-xs mt-2" style={{ color: "var(--danger)" }}>{error}</p>}
    </form>
  );
}
