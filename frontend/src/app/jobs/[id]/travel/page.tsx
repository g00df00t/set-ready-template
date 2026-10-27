"use client";

/* Job home, Travel tab (docs/producer-documents-map.md §1.7): everyone's flights
 * in and out — crew and talent — and two things built from them: the car
 * service's copy (legs planned as car service, with a phone number) and who
 * lands together, so people renting cars can give rides.
 *
 * A leg is one journey, an arrival or a departure; a connection is one leg.
 * Whose number the car service gets is per person: talent default to the
 * producer's, crew to their own (the producer, Q9). Every view is worked out by the
 * API (services/travel.py) — nothing is grouped or checked here.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { TimeInput } from "@/components/TimeInput";
import { useToast } from "@/components/Toast";
import { triggerDownload } from "@/lib/download";
import { displaySpan } from "@/lib/jobDates";
import { fmt } from "@/lib/time";

type Direction = "in" | "out";
type Plan = "car_service" | "rental" | "ride" | "own";
interface Leg {
  id?: string;
  direction: Direction;
  date: string;
  carrier: string | null;
  flight: string | null;
  from_airport: string | null;
  depart_time: string | null;
  arrive_date: string | null;
  to_airport: string | null;
  arrive_time: string | null;
  plan: Plan | null;
  ride_with: string | null;
  note: string | null;
  warning?: string | null;
}
interface Person {
  hire_id: string;
  name: string;
  role: string | null;
  kind: "crew" | "talent";
  status: "hold" | "confirmed";
  has_phone: boolean;
  phone: string | null;
  producer_phone: boolean;
  producer_phone_chosen: boolean;
  first_away: string | null;
  last_away: string | null;
  legs: Leg[];
}
interface GroupPerson { hire_id: string; name: string; arrive_time: string | null; flight: string; plan: Plan | null; plan_text: string }
interface Group { date: string; airport: string | null; first: string | null; last: string | null; people: GroupPerson[] }
interface Row { hire_id: string; direction: Direction }
interface Travel {
  people: Person[];
  arrivals: Row[];
  departures: Row[];
  manifest: Row[];
  missing_phone: string[];
  groups: Group[];
  producer_phone: string | null;
}

const PLANS: [Plan, string][] = [["car_service", "Car service"], ["rental", "Rental car"], ["ride", "Ride with…"], ["own", "Own way"]];

function blankLeg(direction: Direction, p: Person): Leg {
  return {
    direction, date: (direction === "in" ? p.first_away : p.last_away) ?? "",
    carrier: null, flight: null, from_airport: null, depart_time: null, arrive_date: null,
    to_airport: null, arrive_time: null, plan: null, ride_with: null, note: null,
  };
}

function time(t: string | null): string {
  return t ? fmt(t) : "";
}

// "PDX 7:00 AM → EWR 3:20 PM", leaving out whatever isn't set yet.
function route(leg: Leg): string {
  const from = [leg.from_airport, time(leg.depart_time)].filter(Boolean).join(" ");
  const to = [leg.to_airport, time(leg.arrive_time)].filter(Boolean).join(" ");
  return from && to ? `${from} → ${to}` : from ? `${from} →` : to ? `→ ${to}` : "";
}

// The form holds times as typed ("3:20 PM"); the API parses them on save.
function forForm(leg: Leg): Leg {
  return { ...leg, depart_time: leg.depart_time ? fmt(leg.depart_time) : null, arrive_time: leg.arrive_time ? fmt(leg.arrive_time) : null };
}

function planText(leg: Leg, people: Person[]): string {
  if (!leg.plan) return leg.note ?? "";
  const base = leg.plan === "ride"
    ? (() => { const o = people.find((x) => x.hire_id === leg.ride_with); return o ? `Ride with ${o.name}` : "Ride"; })()
    : PLANS.find(([v]) => v === leg.plan)![1];
  return leg.note ? `${base} — ${leg.note}` : base;
}

export default function TravelPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Travel | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  // Which leg is open in the form: `${hire_id}:${leg id or "new"}`.
  const [editing, setEditing] = useState<{ key: string; leg: Leg } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<Travel>(`/api/jobs/${id}/travel`).then(setData).catch(() => setLoadError(true));
  }, [id]);
  useEffect(load, [load]);

  async function saveHire(hireId: string, body: Record<string, unknown>): Promise<boolean> {
    setBusy(hireId);
    try {
      await api.put(`/api/jobs/${id}/hires/${hireId}/travel`, body);
      setData(await api.get<Travel>(`/api/jobs/${id}/travel`));
      return true;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Couldn't save that change.";
      if (editing) setFormError(msg); else showToast(`Couldn't save: ${msg}`);
      return false;
    } finally {
      setBusy(null);
    }
  }

  /** Their own phone, as the car service gets it — typed, corrected or
   * cleared here. A new or corrected number reaches their Master Roster entry
   * and day rows too; clearing it clears only this job's copy. */
  async function savePhone(p: Person, phone: string) {
    if (phone.trim() === (p.phone ?? "")) return;
    setBusy(p.hire_id);
    try {
      await api.put(`/api/jobs/${id}/hires/${p.hire_id}`, { phone: phone.trim() || null });
      setData(await api.get<Travel>(`/api/jobs/${id}/travel`));
      showToast(`Saved ${p.name}'s number.`);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that number.");
    } finally {
      setBusy(null);
    }
  }

  // The whole list goes back, as the server holds it, with this one leg swapped in.
  async function saveLeg(p: Person, leg: Leg) {
    setFormError(null);
    const clean = (leg: Leg) => { const { warning, ...rest } = leg; void warning; return rest; };
    const legs = leg.id ? p.legs.map((l) => (l.id === leg.id ? leg : l)) : [...p.legs, leg];
    if (await saveHire(p.hire_id, { travel_legs: legs.map(clean) })) {
      setEditing(null);
      showToast(leg.id ? "Flight saved" : `${leg.direction === "in" ? "Arrival" : "Departure"} added for ${p.name}`);
    }
  }

  async function removeLeg(p: Person, legId: string) {
    const legs = p.legs.filter((l) => l.id !== legId).map(({ warning, ...rest }) => { void warning; return rest; });
    if (await saveHire(p.hire_id, { travel_legs: legs })) {
      setConfirmRemove(null);
      showToast(`Flight removed from ${p.name}`);
    }
  }

  async function saveProducerPhone(value: string) {
    if (value.trim() === (data?.producer_phone ?? "")) return;
    setBusy("producer");
    try {
      await api.put(`/api/jobs/${id}`, { producer_phone: value });
      setData(await api.get<Travel>(`/api/jobs/${id}/travel`));
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save the number.");
    } finally {
      setBusy(null);
    }
  }

  async function download(path: "travel" | "car-service", kind: "xlsx" | "pdf") {
    setBusy(`${path}-${kind}`);
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/${path}/${kind}`);
      triggerDownload(blob, `${path === "travel" ? "Travel" : "Car service"}.${kind}`, filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download that.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <LoadError message="Couldn't load travel." onRetry={load} />;
  if (!data) return <TableSkeleton />;

  const anyLegs = data.arrivals.length + data.departures.length > 0;
  const together = data.groups.filter((g) => g.people.length > 1);
  const carLegs = data.manifest.length;

  return (
    <div>
      {toastNode}

      <div className="flex items-start justify-between gap-4 mb-5 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Travel</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Flights in and out for crew and talent. Who&apos;s away is set on{" "}
            <Link href={`/jobs/${id}/rooming`} style={{ color: "var(--accent-text)" }}>Rooming</Link>; a flight that doesn&apos;t meet those dates gets a note.
          </p>
        </div>
        <div className="grid gap-1.5 justify-items-end">
          <span className="flex items-center gap-2">
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>Travel doc</span>
            <button type="button" onClick={() => download("travel", "xlsx")} disabled={!!busy || !anyLegs} className="btn btn-primary btn-sm">
              {busy === "travel-xlsx" ? "Preparing…" : "Download Excel"}
            </button>
            <button type="button" onClick={() => download("travel", "pdf")} disabled={!!busy || !anyLegs} className="btn btn-secondary btn-sm">
              {busy === "travel-pdf" ? "Preparing…" : "PDF"}
            </button>
          </span>
          <span className="flex items-center gap-2">
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>For the car service</span>
            <button type="button" onClick={() => download("car-service", "xlsx")} disabled={!!busy || !carLegs} className="btn btn-secondary btn-sm">
              {busy === "car-service-xlsx" ? "Preparing…" : "Excel"}
            </button>
            <button type="button" onClick={() => download("car-service", "pdf")} disabled={!!busy || !carLegs} className="btn btn-secondary btn-sm">
              {busy === "car-service-pdf" ? "Preparing…" : "PDF"}
            </button>
          </span>
        </div>
      </div>

      {data.people.length === 0 && (
        <div className="next-step mb-5" role="status">
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span className="next-step-label">Next</span>
            Hire your crew and talent, then add their flights here.
          </p>
          <Link href={`/jobs/${id}/pre-production`} className="btn btn-primary btn-sm">Go to Pre-production</Link>
        </div>
      )}

      {/* The car service */}
      <section className="card p-5 mb-6" aria-labelledby="car-heading">
        <h2 id="car-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Car service</h2>
        <p className="text-xs mt-0.5 mb-3" style={{ color: "var(--text-secondary)" }}>
          Their copy lists every flight planned as car service, with a phone number. Talent get your number unless you say
          otherwise; crew get their own. No emails, roles or rates go on it.
        </p>
        <div className="grid gap-3 md:grid-cols-[16rem_1fr] items-end">
          <div>
            <label htmlFor="producer-phone" className="field-label">Your number for the car service</label>
            <input id="producer-phone" key={data.producer_phone ?? ""} defaultValue={data.producer_phone ?? ""} maxLength={40}
              disabled={busy === "producer"} onBlur={(e) => saveProducerPhone(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
              placeholder="e.g. 555-0100" className="field-input date-text" />
          </div>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            <b className="date-text" style={{ color: "var(--text-primary)" }}>{carLegs}</b>{` ${carLegs === 1 ? "flight" : "flights"} on the car service's copy`}
          </p>
        </div>
        {data.missing_phone.length > 0 && carLegs > 0 && (
          <p className="text-xs mt-3" role="status" style={{ color: "var(--warning)" }}>
            No number to give for {data.missing_phone.join(", ")}.
            {!data.producer_phone ? " Add yours above, or" : ""} add theirs on their card below.
          </p>
        )}
      </section>

      {/* Landing together */}
      {anyLegs && (
        <section className="card p-5 mb-6" aria-labelledby="together-heading">
          <h2 id="together-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Landing together</h2>
          <p className="text-xs mt-0.5 mb-3" style={{ color: "var(--text-secondary)" }}>
            Same airport, landing within an hour of each other — for sharing a ride. Booked people only.
          </p>
          {together.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>Nobody lands within an hour of anyone else at the same airport.</p>
          ) : (
            <div className="grid gap-3">
              {together.map((g, i) => (
                <div key={i} className="grid gap-1 md:grid-cols-[12rem_1fr]">
                  <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                    <DateText>{displaySpan(g.date, g.date)}</DateText>{g.airport && <> · {g.airport}</>}
                    <span className="block text-xs" style={{ color: "var(--text-secondary)" }}>
                      {g.first ? (g.first === g.last ? time(g.first) : `${time(g.first)} – ${time(g.last)}`) : "Landing time not set"}
                    </span>
                  </span>
                  <ul className="text-sm grid gap-0.5">
                    {g.people.map((p) => (
                      <li key={p.hire_id + (p.arrive_time ?? "")} style={{ color: "var(--text-primary)" }}>
                        {p.name}
                        <span className="text-xs ml-2" style={{ color: "var(--text-secondary)" }}>
                          {[p.arrive_time && time(p.arrive_time), p.flight, p.plan_text].filter(Boolean).join(" · ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Everyone's flights */}
      <div className="grid gap-4">
        {data.people.map((p) => {
          const key = (legId: string) => `${p.hire_id}:${legId}`;
          const open = editing?.key.startsWith(`${p.hire_id}:`) ? editing : null;
          return (
            <section key={p.hire_id} className="card p-5" aria-label={`${p.name}'s flights`}>
              <div className="flex items-start justify-between gap-3 flex-wrap mb-2">
                <div>
                  <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{p.name}</span>
                  <span className="text-xs ml-1.5" style={{ color: "var(--text-secondary)" }}>
                    {[p.role, p.kind === "talent" ? "Talent" : null, p.status === "hold" ? "On hold — on no document yet" : null].filter(Boolean).join(" · ")}
                  </span>
                </div>
                <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                  Car service gets
                  <select value={p.producer_phone ? "producer" : "own"} disabled={busy === p.hire_id}
                    onChange={(e) => saveHire(p.hire_id, { car_service_producer_phone: e.target.value === "producer" })}
                    aria-label={`Which number the car service gets for ${p.name}`} className="field-ghost" style={{ width: "auto" }}>
                    <option value="own">{p.has_phone ? "their number" : "their number (none on file)"}</option>
                    <option value="producer">your number</option>
                  </select>
                </label>
              </div>
              {!p.producer_phone && (
                <label className="flex items-center gap-2 text-xs mb-2" style={{ color: "var(--text-secondary)" }}>
                  Their phone
                  <input type="tel" key={`ph-${p.hire_id}-${p.phone ?? ""}`} defaultValue={p.phone ?? ""} maxLength={40}
                    placeholder="None on file" disabled={busy === p.hire_id}
                    aria-label={`Phone for ${p.name}`} className={`${p.phone ? "field-ghost" : "field-input"} date-text`} style={{ width: "14ch" }}
                    onBlur={(e) => savePhone(p, e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
                  {!p.phone && <span style={{ color: "var(--text-muted)" }}>Saved to their Master Roster entry too.</span>}
                </label>
              )}

              {p.legs.length === 0 && !open && (
                <p className="text-sm mb-2" style={{ color: "var(--text-muted)" }}>No flights yet.</p>
              )}

              <div className="grid gap-1.5">
                {p.legs.map((leg) => open?.key === key(leg.id!) ? (
                  <LegForm key={leg.id} leg={open.leg} people={data.people} self={p} busy={busy === p.hire_id} error={formError}
                    onChange={(l) => setEditing({ key: open.key, leg: l })} onCancel={() => { setEditing(null); setFormError(null); }}
                    onSave={() => saveLeg(p, open.leg)} />
                ) : (
                  <div key={leg.id} className="grid gap-x-3 gap-y-0.5 md:grid-cols-[4.5rem_8rem_1fr_auto] items-baseline text-sm">
                    <span className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>{leg.direction === "in" ? "Arrives" : "Leaves"}</span>
                    <DateText>{displaySpan(leg.direction === "in" ? (leg.arrive_date ?? leg.date) : leg.date, leg.direction === "in" ? (leg.arrive_date ?? leg.date) : leg.date)}</DateText>
                    <span style={{ color: "var(--text-primary)" }}>
                      {[[leg.carrier, leg.flight].filter(Boolean).join(" "),
                        route(leg),
                      ].filter(Boolean).join(" · ") || <span style={{ color: "var(--text-muted)" }}>Flight not set</span>}
                      {planText(leg, data.people) && <span className="text-xs ml-2" style={{ color: "var(--text-secondary)" }}>{planText(leg, data.people)}</span>}
                      {leg.warning && <span className="block text-xs" style={{ color: "var(--warning)" }}>{leg.warning}</span>}
                    </span>
                    <span className="flex items-center gap-1">
                      {confirmRemove === leg.id ? (
                        <>
                          <button type="button" className="btn btn-sm btn-confirm-remove" disabled={busy === p.hire_id} onClick={() => removeLeg(p, leg.id!)}>
                            {busy === p.hire_id ? "Removing…" : "Remove this flight"}
                          </button>
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmRemove(null)}>Cancel</button>
                        </>
                      ) : (
                        <>
                          <button type="button" className="btn btn-ghost btn-sm" disabled={!!editing}
                            onClick={() => { setFormError(null); setEditing({ key: key(leg.id!), leg: forForm(leg) }); }}
                            aria-label={`Edit ${p.name}'s ${leg.direction === "in" ? "arrival" : "departure"}`}>Edit</button>
                          <button type="button" className="btn btn-remove" disabled={!!editing} onClick={() => setConfirmRemove(leg.id!)}
                            aria-label={`Remove ${p.name}'s ${leg.direction === "in" ? "arrival" : "departure"}`}>Remove</button>
                        </>
                      )}
                    </span>
                  </div>
                ))}
                {open?.key === key("new") && (
                  <LegForm leg={open.leg} people={data.people} self={p} busy={busy === p.hire_id} error={formError}
                    onChange={(l) => setEditing({ key: open.key, leg: l })} onCancel={() => { setEditing(null); setFormError(null); }}
                    onSave={() => saveLeg(p, open.leg)} />
                )}
              </div>

              {!open && (
                <div className="flex gap-2 mt-3">
                  <button type="button" className="btn btn-secondary btn-sm" disabled={!!editing}
                    onClick={() => { setFormError(null); setEditing({ key: key("new"), leg: blankLeg("in", p) }); }}
                    aria-label={`Add an arrival for ${p.name}`}>+ Arrival</button>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={!!editing}
                    onClick={() => { setFormError(null); setEditing({ key: key("new"), leg: blankLeg("out", p) }); }}
                    aria-label={`Add a departure for ${p.name}`}>+ Departure</button>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function LegForm({ leg, people, self, busy, error, onChange, onCancel, onSave }: {
  leg: Leg; people: Person[]; self: Person; busy: boolean; error: string | null;
  onChange: (l: Leg) => void; onCancel: () => void; onSave: () => void;
}) {
  const set = (patch: Partial<Leg>) => onChange({ ...leg, ...patch });
  const f = (name: string) => `leg-${self.hire_id}-${name}`;
  const what = leg.direction === "in" ? "arrival" : "departure";
  return (
    <form className="card p-4 my-1 grid gap-3" style={{ background: "var(--bg-inset)" }} aria-label={`${self.name}'s ${what}`}
      onSubmit={(e) => { e.preventDefault(); onSave(); }}>
      <div className="flex items-center gap-2">
        <select value={leg.direction} onChange={(e) => set({ direction: e.target.value as Direction })}
          aria-label="Arrival or departure" className="field-input" style={{ width: "auto" }}>
          <option value="in">Arrival</option>
          <option value="out">Departure</option>
        </select>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <div>
          <label htmlFor={f("date")} className="field-label">Flight date</label>
          <DateInput id={f("date")} value={leg.date} onChange={(v) => set({ date: v })} className="field-input" ariaLabel="Flight date" required />
        </div>
        <div>
          <label htmlFor={f("carrier")} className="field-label">Airline</label>
          <input id={f("carrier")} value={leg.carrier ?? ""} onChange={(e) => set({ carrier: e.target.value })} maxLength={40}
            placeholder="e.g. Delta" className="field-input" />
        </div>
        <div>
          <label htmlFor={f("flight")} className="field-label">Flight #</label>
          <input id={f("flight")} value={leg.flight ?? ""} onChange={(e) => set({ flight: e.target.value })} maxLength={40}
            placeholder="DL 401 / DL 88" className="field-input date-text" />
        </div>
        <div>
          <label htmlFor={f("arrive-date")} className="field-label">Lands (if another day)</label>
          <DateInput id={f("arrive-date")} value={leg.arrive_date ?? ""} onChange={(v) => set({ arrive_date: v || null })} min={leg.date}
            className="field-input" ariaLabel="Landing date, if not the flight date" />
        </div>
        <div>
          <label htmlFor={f("from")} className="field-label">From</label>
          <input id={f("from")} value={leg.from_airport ?? ""} onChange={(e) => set({ from_airport: e.target.value })} maxLength={40}
            placeholder="PDX" className="field-input" />
        </div>
        <div>
          <label htmlFor={f("depart")} className="field-label">Departs</label>
          <TimeInput id={f("depart")} value={leg.depart_time ?? ""} onChange={(v) => set({ depart_time: v || null })}
            ariaLabel="Departure time" placeholder="7:00 AM" />
        </div>
        <div>
          <label htmlFor={f("to")} className="field-label">To</label>
          <input id={f("to")} value={leg.to_airport ?? ""} onChange={(e) => set({ to_airport: e.target.value })} maxLength={40}
            placeholder="EWR" className="field-input" />
        </div>
        <div>
          <label htmlFor={f("arrive")} className="field-label">Lands</label>
          <TimeInput id={f("arrive")} value={leg.arrive_time ?? ""} onChange={(v) => set({ arrive_time: v || null })}
            ariaLabel="Landing time" placeholder="3:20 PM" />
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <div>
          <label htmlFor={f("plan")} className="field-label">Getting to {leg.direction === "in" ? "set" : "the airport"}</label>
          <select id={f("plan")} value={leg.plan ?? ""} onChange={(e) => set({ plan: (e.target.value || null) as Plan | null })} className="field-input">
            <option value="">Not decided</option>
            {PLANS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </div>
        {leg.plan === "ride" && (
          <div>
            <label htmlFor={f("ride")} className="field-label">Ride with</label>
            <select id={f("ride")} value={leg.ride_with ?? ""} onChange={(e) => set({ ride_with: e.target.value || null })} className="field-input">
              <option value="">Someone</option>
              {people.filter((x) => x.hire_id !== self.hire_id).map((x) => <option key={x.hire_id} value={x.hire_id}>{x.name}</option>)}
            </select>
          </div>
        )}
        <div className={leg.plan === "ride" ? "md:col-span-2" : "md:col-span-3"}>
          <label htmlFor={f("note")} className="field-label">Note</label>
          <input id={f("note")} value={leg.note ?? ""} onChange={(e) => set({ note: e.target.value })} maxLength={200}
            placeholder="e.g. picks up Sam at baggage claim" className="field-input" />
        </div>
      </div>
      {error && <p className="text-xs" role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !leg.date}>{busy ? "Saving…" : `Save ${what}`}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
