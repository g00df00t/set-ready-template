"use client";

/* Job home, Rooming tab (docs/producer-documents-map.md §1.5). Three parts:
 * the job's hotels (stays with dates, so a move mid-job is two), who's away
 * from home (everyone travels unless marked local or away only some days),
 * and the rooming list itself — one sheet per hotel, downloadable as Excel or
 * PDF for the hotel.
 *
 * Every night and check-out is worked out by the API (services/rooming.py).
 * Clicking a cell records a hand edit — add a night, take one away, late
 * check-out — and the API works the sheet out again. Nothing is recomputed
 * here, so the screen and the file the hotel gets can't disagree.
 *
 * ⚠️ The list goes to the hotel: it shows names, notes and reservation
 * numbers only — never a phone, a rate or per diem.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { DayTypeTag } from "@/components/DayType";
import { useToast } from "@/components/Toast";
import { triggerDownload } from "@/lib/download";
import { DayType, Span, addDays, displaySpan } from "@/lib/jobDates";

// An extra room booked at a stay — the merch room — not anyone's.
interface Room { id?: string; label: string; notes: string | null; reservation: string | null; nights: string[]; late: string[] }
interface Hotel { id?: string; name: string | null; address: string | null; phone: string | null; contact: string | null; check_in: string; check_out: string; rooms?: Room[] }
interface Row {
  kind: "person" | "room"; hire_id: string | null; room_id: string | null;
  name: string; notes: string; reservation: string; cells: Record<string, string>; total: number;
}
interface Sheet {
  hotel: Hotel | null;
  dates: { date: string; types: DayType[]; label: string | null }[];
  rows: Row[];
  totals: Record<string, number>;
  // Heads a night — people only; differs from totals once there's an extra room.
  breakfasts: Record<string, number>;
  total: number;
}
interface Person {
  hire_id: string; name: string; role: string | null;
  away: Span[] | null; dates: string[];
  room_notes: string | null; reservations: Record<string, string>; room_overrides: Record<string, string>;
}
interface Rooming { hotels: Hotel[]; sheets: Sheet[]; unplaced: { hire_id: string; name: string; date: string }[]; people: Person[] }

type AwayMode = "all" | "local" | "some";
const modeOf = (p: Person): AwayMode => (p.away === null ? "all" : p.away.length ? "some" : "local");

// Consecutive dates back into spans, the shape job_hires.away stores.
function toSpans(dates: string[]): Span[] {
  const out: Span[] = [];
  for (const d of [...dates].sort()) {
    const last = out[out.length - 1];
    if (last && addDays(last[1], 1) === d) last[1] = d; else out.push([d, d]);
  }
  return out;
}
const inSpans = (spans: Span[], d: string) => spans.some(([a, b]) => d >= a && d <= b);

export default function RoomingPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Rooming | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [hotels, setHotels] = useState<Hotel[]>([]);
  const [hotelsDirty, setHotelsDirty] = useState(false);
  const [savingHotels, setSavingHotels] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<Rooming>(`/api/jobs/${id}/rooming`).then((r) => {
      setData(r);
      setHotels(r.hotels);
      setHotelsDirty(false);
    }).catch(() => setLoadError(true));
  }, [id]);
  useEffect(load, [load]);

  // Every change goes to the API and the sheet comes back worked out again.
  async function save(path: string, body: unknown, key: string) {
    setBusy(key);
    try {
      await api.put(path, body);
      const r = await api.get<Rooming>(`/api/jobs/${id}/rooming`);
      setData(r);
      if (!hotelsDirty) setHotels(r.hotels);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that change.");
    } finally {
      setBusy(null);
    }
  }

  const saveHire = (p: Person, body: Record<string, unknown>) =>
    save(`/api/jobs/${id}/hires/${p.hire_id}/rooming`, body, p.hire_id);

  async function saveHotels() {
    setSavingHotels(true);
    try {
      // Rooms are edited on the lists below and saved on their own, so send
      // each stay's latest from the server rather than this card's copy.
      const withRooms = hotels.map((h) => ({ ...h, rooms: data?.hotels.find((x) => x.id === h.id)?.rooms ?? h.rooms ?? [] }));
      await api.put(`/api/jobs/${id}/hotels`, { hotels: withRooms });
      setHotelsDirty(false);
      load();
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save the hotels: ${err.message}` : "Couldn't save the hotels.");
    } finally {
      setSavingHotels(false);
    }
  }

  function editHotel(i: number, patch: Partial<Hotel>) {
    setHotels((hs) => hs.map((h, j) => (j === i ? { ...h, ...patch } : h)));
    setHotelsDirty(true);
  }

  function addHotel() {
    // A new stay starts where the last one ends — a hotel move — or spans
    // the job's dates.
    const every = (data?.people ?? []).flatMap((p) => p.dates).sort();
    const last = hotels[hotels.length - 1];
    const check_in = last?.check_out ?? every[0] ?? "";
    const end = every[every.length - 1] ?? check_in;
    setHotels((hs) => [...hs, { name: "", address: null, phone: null, contact: null, check_in, check_out: end > check_in ? end : "" }]);
    setHotelsDirty(true);
  }

  function setMode(p: Person, mode: AwayMode) {
    if (mode === modeOf(p)) return;
    saveHire(p, { away: mode === "all" ? null : mode === "local" ? [] : toSpans(p.dates) });
  }

  function toggleAwayDay(p: Person, d: string) {
    const current = p.away ?? [];
    const days = p.dates.filter((x) => inSpans(current, x));
    const next = days.includes(d) ? days.filter((x) => x !== d) : [...days, d];
    saveHire(p, { away: toSpans(next) });
  }

  // A cell click: a night comes off, an empty date gets one, and a
  // check-out cycles c/o → late c/o → a night again (extending the stay) —
  // without that last step a night taken off by mistake couldn't come back,
  // since its day turns into the check-out. Each undoes the edit it made
  // before writing a new one.
  function clickCell(p: Person, d: string, value: string | undefined) {
    const o = { ...p.room_overrides };
    if (value === "1") { if (o[d] === "night") delete o[d]; else o[d] = "none"; }
    else if (value === "c/o") o[d] = "late";
    else if (value === "late c/o") o[d] = "night";
    else { if (o[d] === "none") delete o[d]; else o[d] = "night"; }
    saveHire(p, { room_overrides: o });
  }

  // Extra rooms: the whole list for one stay, saved together.
  function saveRooms(stay: Hotel, rooms: Room[]) {
    if (stay.id) save(`/api/jobs/${id}/hotels/${stay.id}/rooms`, { rooms }, `rooms:${stay.id}`);
  }
  const roomsOf = (stay: Hotel) => stay.rooms ?? [];

  function addRoom(stay: Hotel, dates: string[]) {
    // Booked for the whole stay to start with; click nights off from there.
    const nights = dates.filter((d) => d < stay.check_out);
    const label = roomsOf(stay).some((r) => r.label === "Merch room") ? "Extra room" : "Merch room";
    saveRooms(stay, [...roomsOf(stay), { label, notes: null, reservation: null, nights, late: [] }]);
  }

  function editRoom(stay: Hotel, roomId: string, patch: Partial<Room>) {
    saveRooms(stay, roomsOf(stay).map((r) => (r.id === roomId ? { ...r, ...patch } : r)));
  }

  function clickRoomCell(stay: Hotel, room: Room, d: string, value: string | undefined) {
    if (value === "1") editRoom(stay, room.id!, { nights: room.nights.filter((n) => n !== d) });
    else if (value === "c/o") editRoom(stay, room.id!, { late: [...room.late, d] });
    else if (value === "late c/o")
      // Same cycle as a person's: late check-out → a night again, if the stay
      // still has that night (its own check-out day can't be one).
      editRoom(stay, room.id!, {
        late: room.late.filter((n) => n !== d),
        nights: d < stay.check_out ? [...room.nights, d].sort() : room.nights,
      });
    else if (d < stay.check_out) editRoom(stay, room.id!, { nights: [...room.nights, d].sort() });
  }

  async function download(sheet: Sheet, kind: "xlsx" | "pdf") {
    const key = sheet.hotel?.id ?? "all";
    setBusy(`${key}:${kind}`);
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/rooming/${key}/${kind}`);
      triggerDownload(blob, `Rooming list.${kind}`, filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download the rooming list.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <LoadError message="Couldn't load the rooming list." onRetry={load} />;
  if (!data) return <TableSkeleton />;

  const person = (hid: string) => data.people.find((p) => p.hire_id === hid)!;

  return (
    <div>
      {toastNode}

      {/* Hotels */}
      <section className="card p-5 mb-6" aria-labelledby="hotels-heading">
        <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
          <div>
            <h2 id="hotels-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Hotels</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              Each stay with its dates. Moving hotels mid-job? Add a second stay starting the day the first ends.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={addHotel} className="btn btn-secondary btn-sm">+ Add hotel</button>
            {hotelsDirty && (
              <button type="button" onClick={saveHotels} disabled={savingHotels} className="btn btn-primary btn-sm">
                {savingHotels ? "Saving…" : "Save hotels"}
              </button>
            )}
          </div>
        </div>
        {hotels.length === 0 && (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            No hotel yet. The list below still shows everyone&apos;s nights; add the hotel to put its name, dates and reservation numbers on it.
          </p>
        )}
        <div className="grid gap-4">
          {hotels.map((h, i) => (
            <div key={h.id ?? `new-${i}`} className="grid gap-3 md:grid-cols-6 items-end">
              <div className="md:col-span-2">
                <label htmlFor={`hotel-name-${i}`} className="field-label">Hotel</label>
                <input id={`hotel-name-${i}`} value={h.name ?? ""} onChange={(e) => editHotel(i, { name: e.target.value })}
                  placeholder="e.g. The Oxford Hotel" className="field-input" />
              </div>
              <div>
                <label htmlFor={`hotel-in-${i}`} className="field-label">Check-in</label>
                <DateInput id={`hotel-in-${i}`} value={h.check_in} onChange={(v) => editHotel(i, { check_in: v })} className="field-input"
                  ariaLabel={`Check-in${h.name ? ` at ${h.name}` : ""}`} />
              </div>
              <div>
                <label htmlFor={`hotel-out-${i}`} className="field-label">Check-out</label>
                <DateInput id={`hotel-out-${i}`} value={h.check_out} onChange={(v) => editHotel(i, { check_out: v })} className="field-input"
                  ariaLabel={`Check-out${h.name ? ` at ${h.name}` : ""}`} />
              </div>
              <div>
                <label htmlFor={`hotel-contact-${i}`} className="field-label">Contact</label>
                <input id={`hotel-contact-${i}`} value={h.contact ?? ""} onChange={(e) => editHotel(i, { contact: e.target.value })}
                  placeholder="e.g. Group sales" className="field-input" />
              </div>
              <div>
                <button type="button" className="btn btn-remove"
                  onClick={() => { setHotels((hs) => hs.filter((_, j) => j !== i)); setHotelsDirty(true); }}
                  aria-label={`Remove ${h.name || "this hotel"}`}>
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Who's away */}
      <section className="card p-5 mb-6" aria-labelledby="away-heading">
        <h2 id="away-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Who&apos;s away</h2>
        <p className="text-xs mt-0.5 mb-3" style={{ color: "var(--text-secondary)" }}>
          Everyone travels unless you say otherwise. A night is every day away but the last, which is check-out.
        </p>
        {data.people.length === 0 && (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>Nobody hired yet — hire on Pre-production first.</p>
        )}
        <div className="grid gap-2">
          {data.people.map((p) => {
            const mode = modeOf(p);
            return (
              <div key={p.hire_id} className="grid gap-2 md:grid-cols-[14rem_10rem_1fr] items-center">
                <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                  {p.name}{p.role && <span className="text-xs ml-1.5" style={{ color: "var(--text-secondary)" }}>{p.role}</span>}
                </span>
                <select value={mode} onChange={(e) => setMode(p, e.target.value as AwayMode)} disabled={busy === p.hire_id}
                  aria-label={`Is ${p.name} away from home?`} className="field-input">
                  <option value="all">Traveling</option>
                  <option value="local">Local</option>
                  <option value="some">Some days</option>
                </select>
                {mode === "some" ? (
                  <span className="flex flex-wrap gap-1" role="group" aria-label={`Days ${p.name} is away`}>
                    {p.dates.map((d) => {
                      const on = inSpans(p.away ?? [], d);
                      return (
                        <button key={d} type="button" aria-pressed={on} disabled={busy === p.hire_id}
                          aria-label={`${displaySpan(d, d)}: ${on ? "away" : "home"}`}
                          onClick={() => toggleAwayDay(p, d)}
                          className={`btn btn-sm ${on ? "btn-secondary" : "btn-ghost"}`}>
                          <DateText>{displaySpan(d, d)}</DateText>
                        </button>
                      );
                    })}
                  </span>
                ) : (
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {mode === "local" ? "Lives here — no nights, no per diem" : p.dates.length ? `Away all ${p.dates.length} of their days` : "No dates yet"}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {data.unplaced.length > 0 && (
        <div className="card p-4 mb-6" role="status" style={{ borderColor: "var(--warning)" }}>
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            {data.unplaced.length} {data.unplaced.length === 1 ? "night isn't" : "nights aren't"} in any hotel&apos;s dates:{" "}
            {data.unplaced.map((u) => `${u.name} ${displaySpan(u.date, u.date)}`).join(", ")}. Stretch a stay or add one.
          </p>
        </div>
      )}

      {/* The rooming lists */}
      {data.sheets.map((sheet) => {
        const key = sheet.hotel?.id ?? "all";
        return (
          <section key={key} className="mb-8" aria-label={`Rooming list${sheet.hotel?.name ? ` for ${sheet.hotel.name}` : ""}`}>
            <div className="flex items-center justify-between gap-4 mb-3 flex-wrap">
              <div>
                <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
                  Rooming list{sheet.hotel?.name ? ` · ${sheet.hotel.name}` : ""}
                </h2>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  Goes to the hotel: names, notes and reservation numbers only. Click a night to take it off or add one; click a check-out to make it late, and again to make it a night.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => download(sheet, "xlsx")} disabled={!!busy || !sheet.rows.length} className="btn btn-primary btn-sm">
                  {busy === `${key}:xlsx` ? "Preparing…" : "Download Excel"}
                </button>
                <button type="button" onClick={() => download(sheet, "pdf")} disabled={!!busy || !sheet.rows.length} className="btn btn-secondary btn-sm">
                  {busy === `${key}:pdf` ? "Preparing…" : "PDF"}
                </button>
              </div>
            </div>
            <div className="data-table-raised">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Notes</th>
                    {sheet.hotel && <th>Reservation #</th>}
                    {sheet.dates.map((c) => (
                      <th key={c.date} style={{ textAlign: "center" }}>
                        <span className="grid justify-items-center gap-0.5">
                          <DateText>{displaySpan(c.date, c.date)}</DateText>
                          {c.types.map((t) => <DayTypeTag key={t} type={t} />)}
                        </span>
                      </th>
                    ))}
                    <th style={{ textAlign: "center" }}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {sheet.rows.length === 0 && (
                    <tr><td colSpan={sheet.dates.length + 4} className="text-sm" style={{ color: "var(--text-muted)" }}>
                      Nobody has a night here.
                    </td></tr>
                  )}
                  {sheet.rows.map((r) => {
                    if (r.kind === "room" && sheet.hotel) {
                      const stay = sheet.hotel;
                      const room = roomsOf(stay).find((x) => x.id === r.room_id);
                      if (!room) return null;
                      const roomBusy = busy === `rooms:${stay.id}`;
                      return (
                        <tr key={`room-${r.room_id}`}>
                          <td>
                            <input key={room.label} defaultValue={room.label} maxLength={200}
                              onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== room.label) editRoom(stay, room.id!, { label: v }); }}
                              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                              aria-label="Extra room name" className="field-ghost text-sm font-medium" />
                            <button type="button" className="btn btn-remove" style={{ marginLeft: "-0.375rem", paddingLeft: "0.375rem", paddingRight: "0.375rem" }}
                              disabled={roomBusy} onClick={() => saveRooms(stay, roomsOf(stay).filter((x) => x.id !== room.id))}
                              aria-label={`Remove ${room.label}`}>
                              Remove
                            </button>
                          </td>
                          <td>
                            <input key={room.notes ?? ""} defaultValue={room.notes ?? ""} maxLength={200}
                              onBlur={(e) => { if (e.target.value.trim() !== (room.notes ?? "")) editRoom(stay, room.id!, { notes: e.target.value }); }}
                              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                              placeholder="—" aria-label={`Note for ${room.label}`} className="field-ghost" />
                          </td>
                          <td>
                            <input key={room.reservation ?? ""} defaultValue={room.reservation ?? ""} maxLength={80}
                              onBlur={(e) => { if (e.target.value.trim() !== (room.reservation ?? "")) editRoom(stay, room.id!, { reservation: e.target.value }); }}
                              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                              placeholder="—" aria-label={`Reservation number for ${room.label}`} className="field-ghost date-text" />
                          </td>
                          {sheet.dates.map((c) => {
                            const v = r.cells[c.date];
                            const canAdd = !v && c.date < stay.check_out;
                            return (
                              <td key={c.date} style={{ padding: "0.375rem", textAlign: "center" }}>
                                <button type="button" className="cell-btn" disabled={roomBusy || (!v && !canAdd)}
                                  onClick={() => clickRoomCell(stay, room, c.date, v)}
                                  aria-label={`${room.label}, ${displaySpan(c.date, c.date)}: ${v === "1" ? "a night — click to remove" : v === "c/o" ? "check-out — click for a late check-out" : v ? (c.date < stay.check_out ? "late check-out — click to make it a night" : "late check-out — click for a normal one") : canAdd ? "no night — click to add one" : "check-out day"}`}
                                  style={{ justifyItems: "center" }}>
                                  {v === "1" ? <DateText>1</DateText>
                                    : v ? <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{v}</span>
                                      : <span className="empty">·</span>}
                                </button>
                              </td>
                            );
                          })}
                          <td style={{ textAlign: "center" }}><DateText>{r.total}</DateText></td>
                        </tr>
                      );
                    }
                    const p = person(r.hire_id!);
                    return (
                      <tr key={r.hire_id!}>
                        <td className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{r.name}</td>
                        <td>
                          <input
                            key={p.room_notes ?? ""} defaultValue={p.room_notes ?? ""} maxLength={200}
                            onBlur={(e) => { if (e.target.value.trim() !== (p.room_notes ?? "")) saveHire(p, { room_notes: e.target.value }); }}
                            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                            placeholder="—" aria-label={`Room note for ${r.name}`} className="field-ghost"
                          />
                        </td>
                        {sheet.hotel && (
                          <td>
                            <input
                              key={r.reservation} defaultValue={r.reservation} maxLength={80}
                              onBlur={(e) => {
                                const v = e.target.value.trim();
                                if (v !== r.reservation && sheet.hotel?.id)
                                  saveHire(p, { reservations: { ...p.reservations, [sheet.hotel.id]: v } });
                              }}
                              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                              placeholder="—" aria-label={`Reservation number for ${r.name}`} className="field-ghost date-text"
                            />
                          </td>
                        )}
                        {sheet.dates.map((c) => {
                          const v = r.cells[c.date];
                          return (
                            <td key={c.date} style={{ padding: "0.375rem", textAlign: "center" }}>
                              <button type="button" className="cell-btn" disabled={busy === r.hire_id}
                                onClick={() => clickCell(p, c.date, v)}
                                aria-label={`${r.name}, ${displaySpan(c.date, c.date)}: ${v === "1" ? "a night — click to remove" : v === "c/o" ? "check-out — click for a late check-out" : v ? "late check-out — click to make it a night" : "no night — click to add one"}`}
                                style={{ justifyItems: "center" }}>
                                {v === "1" ? <DateText>1</DateText>
                                  : v ? <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{v}</span>
                                    : <span className="empty">·</span>}
                              </button>
                            </td>
                          );
                        })}
                        <td style={{ textAlign: "center" }}><DateText>{r.total}</DateText></td>
                      </tr>
                    );
                  })}
                  {sheet.rows.length > 0 && (
                    <tr>
                      <td className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }} colSpan={sheet.hotel ? 3 : 2}>
                        Rooms a night
                      </td>
                      {sheet.dates.map((c) => (
                        <td key={c.date} style={{ textAlign: "center" }}><DateText>{sheet.totals[c.date] ?? 0}</DateText></td>
                      ))}
                      <td style={{ textAlign: "center" }}><DateText>{sheet.total}</DateText></td>
                    </tr>
                  )}
                  {sheet.rows.some((r) => r.kind === "room") && (
                    <tr>
                      <td className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }} colSpan={3}>
                        Breakfasts
                      </td>
                      {sheet.dates.map((c) => (
                        <td key={c.date} style={{ textAlign: "center" }}><DateText>{sheet.breakfasts[c.date] ?? 0}</DateText></td>
                      ))}
                      <td />
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {sheet.hotel?.id && (
              <button type="button" onClick={() => addRoom(sheet.hotel!, sheet.dates.map((c) => c.date))}
                disabled={busy === `rooms:${sheet.hotel.id}`} className="btn btn-ghost btn-sm mt-2">
                + Add a room that isn&apos;t a person&apos;s (merch, gear)
              </button>
            )}
          </section>
        );
      })}
    </div>
  );
}
