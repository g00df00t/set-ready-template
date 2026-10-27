"use client";

/* Job home, Vendors tab (docs/producer-documents-map.md §1.9, §2.5): the
 * business side of everything the job books — the hotel, each day's
 * location, permits, the motorhome, caterers, rentals — with the producer's
 * four-step checklist: COI requested · Signed agreement · Deposit · Final bill.
 *
 * Linked, not copied: a hotel booking points at a stay on Rooming and a
 * location booking at a day, and their names and addresses are read from
 * there. A step is done when it has a date; the payments carry an amount.
 * Everything shown is worked out by the API (services/vendors.py).
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateText } from "@/components/DateText";
import { useToast } from "@/components/Toast";
import { displaySpan } from "@/lib/jobDates";
import { money } from "@/lib/rates";

type Kind = "hotel" | "location" | "permit" | "motorhome" | "caterer" | "rentals" | "other";
type StepKey = "coi" | "agreement" | "deposit" | "final_bill";
interface Step { date: string | null; amount?: number | null }
interface Vendor {
  id?: string;
  kind: Kind;
  name: string | null;
  hotel_id: string | null;
  day_id: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  website: string | null;
  fee: number | null;
  fee_note: string | null;
  steps: Partial<Record<StepKey, Step>>;
  notes: string | null;
}
interface Resolved extends Vendor { id: string; title: string; subtitle: string; broken: boolean; missing: StepKey[]; kind_label: string }
interface View {
  vendors: Resolved[];
  open_items: { vendor_id: string; title: string; kind: string; missing: string[] }[];
  unbooked: { hotels: { hotel_id: string; title: string; subtitle: string }[]; days: { day_id: string; title: string; subtitle: string }[] };
  hotels: { id: string; name: string }[];
  days: { id: string; shoot_date: string | null; location: string | null }[];
  kinds: Record<Kind, string>;
  steps: Record<StepKey, string>;
}

const STEP_ORDER: StepKey[] = ["coi", "agreement", "deposit", "final_bill"];
const MONEY: StepKey[] = ["deposit", "final_bill"];

// A payment as typed back into its box: cents always two places ("1240.50",
// not "1240.5"), whole dollars bare. 12ch fits any amount up to the $10M cap.
function amountText(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "";
  return Number.isInteger(amount) ? String(amount) : amount.toFixed(2);
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function blank(kind: Kind, link: Partial<Vendor> = {}): Vendor {
  return { kind, name: null, hotel_id: null, day_id: null, contact_name: null, contact_phone: null, contact_email: null,
    website: null, fee: null, fee_note: null, steps: {}, notes: null, ...link };
}

// What goes back to the API: the stored fields only, not what it worked out.
function stored(v: Vendor | Resolved): Vendor {
  const { id, kind, name, hotel_id, day_id, contact_name, contact_phone, contact_email, website, fee, fee_note, steps, notes } = v;
  return { id, kind, name, hotel_id, day_id, contact_name, contact_phone, contact_email, website, fee, fee_note, steps, notes };
}

export default function VendorsPage() {
  const { id } = useParams<{ id: string }>();
  const [view, setView] = useState<View | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<Vendor | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<View>(`/api/jobs/${id}/vendors`).then(setView).catch(() => setLoadError(true));
  }, [id]);
  useEffect(load, [load]);

  async function saveEdit() {
    if (!editing) return;
    setBusy("form"); setFormError(null);
    try {
      const body = { vendor: stored(editing) };
      setView(editing.id
        ? await api.put<View>(`/api/jobs/${id}/vendors/${editing.id}`, body)
        : await api.post<View>(`/api/jobs/${id}/vendors`, body));
      showToast(editing.id ? "Booking saved" : "Booking added");
      setEditing(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Couldn't save the booking.");
    } finally {
      setBusy(null);
    }
  }

  // A one-click change to a booking that's already saved: a checklist step,
  // an amount. Saved as it's made; on failure, a toast and the server's copy.
  async function patch(v: Resolved, change: Partial<Vendor>) {
    setBusy(v.id);
    try {
      setView(await api.put<View>(`/api/jobs/${id}/vendors/${v.id}`, { vendor: { ...stored(v), ...change } }));
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that.");
      load();
    } finally {
      setBusy(null);
    }
  }

  function toggleStep(v: Resolved, key: StepKey) {
    const steps = { ...v.steps };
    if (steps[key]?.date) delete steps[key];
    else steps[key] = { ...(steps[key] ?? {}), date: today() };
    patch(v, { steps });
  }

  function setAmount(v: Resolved, key: StepKey, raw: string) {
    const amount = raw.trim() === "" ? null : Number(raw.replace(/[^0-9.]/g, ""));
    if ((v.steps[key]?.amount ?? null) === amount) return;
    patch(v, { steps: { ...v.steps, [key]: { date: v.steps[key]?.date ?? null, amount } } });
  }

  async function remove(v: Resolved) {
    setBusy(v.id);
    try {
      setView(await api.delete<View>(`/api/jobs/${id}/vendors/${v.id}`));
      setConfirmRemove(null);
      showToast(`${v.title} removed`);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't remove: ${err.message}` : "Couldn't remove it.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <LoadError message="Couldn't load the vendors." onRetry={load} />;
  if (!view) return <TableSkeleton />;

  const kinds = Object.keys(view.kinds) as Kind[];
  const grouped = kinds.map((k) => ({ kind: k, items: view.vendors.filter((v) => v.kind === k) })).filter((g) => g.items.length);
  const offers = view.unbooked.hotels.length + view.unbooked.days.length;

  return (
    <div>
      {toastNode}

      <div className="flex items-start justify-between gap-4 mb-5 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Vendors</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Everything the job books, with its checklist: COI requested · Signed agreement · Deposit · Final bill. The final bill is the balance after the deposit — each payment goes on the PC log as its own line.
            Hotels come from <Link href={`/jobs/${id}/rooming`} style={{ color: "var(--accent-text)" }}>Rooming</Link>,
            locations from each day.
          </p>
        </div>
        {!editing && (
          <label className="flex items-center gap-2">
            <span className="sr-only">Add a booking</span>
            <select value="" onChange={(e) => { if (e.target.value) { setFormError(null); setEditing(blank(e.target.value as Kind)); } }}
              className="btn btn-primary btn-sm" aria-label="Add a booking of this kind">
              <option value="">+ Add booking</option>
              {kinds.map((k) => <option key={k} value={k}>{view.kinds[k]}</option>)}
            </select>
          </label>
        )}
      </div>

      {view.open_items.length > 0 && (
        <section className="card p-4 mb-5" aria-labelledby="open-heading">
          <h3 id="open-heading" className="day-label warn mb-2">Still to do</h3>
          <ul className="grid gap-1 text-sm">
            {view.open_items.map((o) => (
              <li key={o.vendor_id} style={{ color: "var(--text-primary)" }}>
                {o.title} <span className="text-xs" style={{ color: "var(--text-muted)" }}>{o.kind}</span>
                <span className="text-xs ml-2" style={{ color: "var(--text-secondary)" }}>{o.missing.join(" · ")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {editing && (
        <VendorForm vendor={editing} view={view} busy={busy === "form"} error={formError}
          onChange={setEditing} onCancel={() => { setEditing(null); setFormError(null); }} onSave={saveEdit} />
      )}

      {offers > 0 && !editing && (
        <div className="grid gap-2 mb-5">
          {view.unbooked.hotels.map((h) => (
            <div key={h.hotel_id} className="card-placeholder flex items-center justify-between gap-3 p-3">
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                <span className="day-label muted mr-2">Hotel</span>{h.title}
                <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>{h.subtitle} · no booking yet</span>
              </span>
              <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => { setFormError(null); setEditing(blank("hotel", { hotel_id: h.hotel_id })); }}
                aria-label={`Add a booking for ${h.title}, ${h.subtitle}`}>Add booking</button>
            </div>
          ))}
          {view.unbooked.days.map((d) => (
            <div key={d.day_id} className="card-placeholder flex items-center justify-between gap-3 p-3">
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                <span className="day-label muted mr-2">Location</span>{d.title}
                <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>{d.subtitle} · no booking yet</span>
              </span>
              <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => { setFormError(null); setEditing(blank("location", { day_id: d.day_id })); }}
                aria-label={`Add a booking for ${d.title}, ${d.subtitle}`}>Add booking</button>
            </div>
          ))}
        </div>
      )}

      {view.vendors.length === 0 && offers === 0 && !editing && (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          No bookings yet. Add a hotel on Rooming or a location on a day and it&apos;s offered here, or add a permit, motorhome or caterer above.
        </p>
      )}

      <div className="grid gap-6">
        {grouped.map((g) => (
          <section key={g.kind} aria-label={view.kinds[g.kind]}>
            <h3 className="day-label mb-2">{view.kinds[g.kind]}</h3>
            <div className="grid gap-3">
              {g.items.map((v) => (
                <article key={v.id} className="card p-4" aria-label={v.title}>
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div>
                      <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{v.title}</p>
                      {v.subtitle && <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{v.subtitle}</p>}
                      {v.broken && (
                        <p className="text-xs mt-0.5" style={{ color: "var(--warning)" }}>
                          The {v.kind === "hotel" ? "hotel stay" : "day"} this was for has been removed. Edit it to link another, or remove it.
                        </p>
                      )}
                      {(v.contact_name || v.contact_phone || v.contact_email) && (
                        <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                          {[v.contact_name, v.contact_phone, v.contact_email].filter(Boolean).join(" · ")}
                        </p>
                      )}
                      {v.website && (
                        <a href={v.website} target="_blank" rel="noopener noreferrer" className="text-xs" style={{ color: "var(--accent-text)" }}>
                          {v.website.replace(/^https?:\/\//, "")}
                        </a>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {v.fee != null && <DateText>{money(v.fee)}</DateText>}
                      {v.fee_note && <span className="text-xs ml-1" style={{ color: "var(--text-muted)" }}>{v.fee_note}</span>}
                      {confirmRemove === v.id ? (
                        <>
                          <button type="button" className="btn btn-sm btn-confirm-remove ml-2" disabled={busy === v.id} onClick={() => remove(v)}>
                            {busy === v.id ? "Removing…" : `Remove ${v.title}`}
                          </button>
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmRemove(null)}>Cancel</button>
                        </>
                      ) : (
                        <>
                          <button type="button" className="btn btn-ghost btn-sm ml-2" disabled={!!editing}
                            onClick={() => { setFormError(null); setEditing(stored(v)); }} aria-label={`Edit ${v.title}`}>Edit</button>
                          <button type="button" className="btn btn-remove" disabled={!!editing}
                            onClick={() => setConfirmRemove(v.id)} aria-label={`Remove ${v.title}`}>Remove</button>
                        </>
                      )}
                    </div>
                  </div>

                  {v.kind !== "caterer" && (
                    <div className="flex flex-wrap gap-2 mt-3" role="group" aria-label={`${v.title} checklist`}>
                      {STEP_ORDER.map((k) => {
                        const step = v.steps[k];
                        const done = !!step?.date;
                        return (
                          <span key={k} className="flex items-center gap-1">
                            <button type="button" aria-pressed={done} disabled={busy === v.id}
                              onClick={() => toggleStep(v, k)}
                              className={`btn btn-sm ${done ? "btn-secondary" : "btn-ghost"}`}
                              aria-label={`${view.steps[k]}${done ? `, done ${step!.date}. Click to undo` : ", not done. Click to mark done today"}`}>
                              <span style={{ color: done ? "var(--success)" : "var(--text-muted)" }}>{done ? "✓" : "○"}</span>
                              {view.steps[k]}
                              {done && <DateText muted>{displaySpan(step!.date!, step!.date!)}</DateText>}
                            </button>
                            {MONEY.includes(k) && (
                              <span className="flex items-center">
                                <span className="date-text text-xs" style={{ color: "var(--text-muted)" }}>$</span>
                                <input key={`${v.id}-${k}-${step?.amount ?? ""}`} defaultValue={amountText(step?.amount)} inputMode="decimal"
                                  onBlur={(e) => setAmount(v, k, e.target.value)}
                                  onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                                  aria-label={`${view.steps[k]} amount for ${v.title}`} placeholder="—"
                                  className="field-ghost date-text" style={{ width: "12ch" }} />
                              </span>
                            )}
                          </span>
                        );
                      })}
                    </div>
                  )}
                  {v.notes && <p className="text-sm mt-3" style={{ color: "var(--text-secondary)", whiteSpace: "pre-line" }}>{v.notes}</p>}
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function VendorForm({ vendor, view, busy, error, onChange, onCancel, onSave }: {
  vendor: Vendor; view: View; busy: boolean; error: string | null;
  onChange: (v: Vendor) => void; onCancel: () => void; onSave: () => void;
}) {
  const set = (patch: Partial<Vendor>) => onChange({ ...vendor, ...patch });
  const text = (field: keyof Vendor) => ({
    value: (vendor[field] as string | null) ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set({ [field]: e.target.value || null } as Partial<Vendor>),
  });
  const linked = vendor.kind === "hotel" || vendor.kind === "location";
  return (
    <form className="card p-5 mb-5 grid gap-4" aria-label={`${vendor.id ? "Edit" : "New"} ${view.kinds[vendor.kind].toLowerCase()} booking`}
      onSubmit={(e) => { e.preventDefault(); onSave(); }}>
      <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>
        {vendor.id ? "Edit" : "New"} {view.kinds[vendor.kind].toLowerCase()} booking
      </h3>
      <div className="grid gap-3 md:grid-cols-3">
        {vendor.kind === "hotel" && (
          <div>
            <label htmlFor="v-hotel" className="field-label">Hotel stay</label>
            <select id="v-hotel" value={vendor.hotel_id ?? ""} onChange={(e) => set({ hotel_id: e.target.value || null })} className="field-input" required>
              <option value="">Pick a stay from Rooming</option>
              {view.hotels.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          </div>
        )}
        {vendor.kind === "location" && (
          <div>
            <label htmlFor="v-day" className="field-label">Day</label>
            <select id="v-day" value={vendor.day_id ?? ""} onChange={(e) => set({ day_id: e.target.value || null })} className="field-input" required>
              <option value="">Pick a day</option>
              {view.days.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.shoot_date ? displaySpan(d.shoot_date, d.shoot_date) : "No date"}{d.location ? ` · ${d.location}` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        {!linked && (
          <div>
            <label htmlFor="v-name" className="field-label">Name</label>
            <input id="v-name" {...text("name")} maxLength={120} required placeholder="e.g. Star Coach Motorhomes" className="field-input" />
          </div>
        )}
        <div>
          <label htmlFor="v-fee" className="field-label">Fee</label>
          <span className="flex items-center gap-1">
            <span className="date-text" style={{ color: "var(--text-muted)" }}>$</span>
            <input id="v-fee" inputMode="decimal" value={vendor.fee ?? ""} className="field-input date-text"
              onChange={(e) => { const v = e.target.value.replace(/[^0-9.]/g, ""); set({ fee: v === "" ? null : Number(v) }); }} />
          </span>
        </div>
        <div>
          <label htmlFor="v-fee-note" className="field-label">Fee note</label>
          <input id="v-fee-note" {...text("fee_note")} maxLength={200} placeholder="e.g. per day, plus tax" className="field-input" />
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <div>
          <label htmlFor="v-contact" className="field-label">Contact</label>
          <input id="v-contact" {...text("contact_name")} maxLength={120} placeholder="e.g. Group sales" className="field-input" />
        </div>
        <div>
          <label htmlFor="v-phone" className="field-label">Phone</label>
          <input id="v-phone" type="tel" {...text("contact_phone")} maxLength={40} className="field-input date-text" />
        </div>
        <div>
          <label htmlFor="v-email" className="field-label">Email</label>
          <input id="v-email" type="email" {...text("contact_email")} maxLength={160} className="field-input" />
        </div>
        <div>
          <label htmlFor="v-web" className="field-label">Website</label>
          <input id="v-web" {...text("website")} maxLength={300} placeholder="example.com" className="field-input" />
        </div>
      </div>
      <div>
        <label htmlFor="v-notes" className="field-label">Notes</label>
        <textarea id="v-notes" rows={4} {...text("notes")} maxLength={2000} className="field-input"
          placeholder={vendor.kind === "location" ? "Hours, site rep, location manager, crew size, staging area, rules…"
            : vendor.kind === "caterer" ? "Menus, delivery or pick-up…" : "Anything to remember"} />
      </div>
      {error && <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{busy ? "Saving…" : vendor.id ? "Save booking" : "Add booking"}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
