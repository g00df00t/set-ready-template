"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { fmt } from "@/lib/time";
import { TimeInput } from "@/components/TimeInput";
import { useToast } from "@/components/Toast";

interface Location {
  location_name: string;
  address: string;
  parking_notes: string;
  parking_address: string;
  additional_notes: string;
}

interface RosterEntry {
  id: string;
  name: string;
  address: string | null;
  parking_notes: string | null;
  parking_address: string | null;
  additional_notes: string | null;
}

interface CompanyMove {
  id: string;
  label: string | null;
  location_name: string | null;
  address: string | null;
  parking_notes: string | null;
  parking_address: string | null;
  additional_notes: string | null;
  move_time: string | null;
  sort_order: number;
}

interface MoveForm {
  label: string;
  location_name: string;
  address: string;
  parking_notes: string;
  parking_address: string;
  additional_notes: string;
  move_time: string;
}

const emptyMoveForm: MoveForm = {
  label: "", location_name: "", address: "", parking_notes: "", parking_address: "", additional_notes: "", move_time: "",
};


function MoveFields({ values, onChange }: { values: MoveForm; onChange: (key: keyof MoveForm, val: string) => void }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div><label className="field-label">Move time</label><TimeInput value={values.move_time} onChange={(v) => onChange("move_time", v)} /></div>
        <div><label className="field-label">Label</label><input aria-label="Label" value={values.label} onChange={(e) => onChange("label", e.target.value)} placeholder="Afternoon location…" className="field-input" /></div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div><label className="field-label">Location name</label><input aria-label="Location name" value={values.location_name} onChange={(e) => onChange("location_name", e.target.value)} placeholder="Studio B, Rooftop…" className="field-input" /></div>
        <div><label className="field-label">Address</label><input aria-label="Address" value={values.address} onChange={(e) => onChange("address", e.target.value)} placeholder="123 Main St, Seattle, WA" className="field-input" /></div>
      </div>
      <div><label className="field-label">Parking instructions</label><textarea aria-label="Parking instructions" rows={2} value={values.parking_notes} onChange={(e) => onChange("parking_notes", e.target.value)} placeholder="Street parking on 3rd Ave" className="field-input resize-none" /></div>
      <div><label className="field-label">Parking address <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(if different from location)</span></label><input aria-label="Parking address" value={values.parking_address} onChange={(e) => onChange("parking_address", e.target.value)} placeholder="456 Parking St, Seattle, WA" className="field-input" /></div>
      <div><label className="field-label">Additional notes</label><textarea aria-label="Additional notes" rows={2} value={values.additional_notes} onChange={(e) => onChange("additional_notes", e.target.value)} placeholder="Check in with security" className="field-input resize-none" /></div>
    </div>
  );
}

export default function LocationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [form, setForm] = useState<Location>({ location_name: "", address: "", parking_notes: "", parking_address: "", additional_notes: "" });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [canContinue, setCanContinue] = useState(false);
  const [error, setError] = useState("");
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [moves, setMoves] = useState<CompanyMove[]>([]);
  const [showMoveForm, setShowMoveForm] = useState(false);
  const [moveForm, setMoveForm] = useState<MoveForm>(emptyMoveForm);
  const [moveSaving, setMoveSaving] = useState(false);
  const [moveError, setMoveError] = useState("");
  const [editingMoveId, setEditingMoveId] = useState<string | null>(null);
  const [editMoveForm, setEditMoveForm] = useState<MoveForm>(emptyMoveForm);
  const [editMoveSaving, setEditMoveSaving] = useState(false);
  const { show: showToast, node: toastNode } = useToast();

  useEffect(() => {
    api.get<Location>(`/api/projects/${id}/location`).then((data) => {
      if (data.address) setCanContinue(true);
      setForm({ location_name: data.location_name ?? "", address: data.address ?? "", parking_notes: data.parking_notes ?? "", parking_address: data.parking_address ?? "", additional_notes: data.additional_notes ?? "" });
    }).catch(() => {});
    api.get<CompanyMove[]>(`/api/projects/${id}/company-moves`).then(setMoves).catch(() => {});
    api.get<RosterEntry[]>("/api/location-roster").then(setRoster).catch(() => {});
  }, [id]);

  function fillFromRoster(entryId: string) {
    const entry = roster.find((r) => r.id === entryId);
    if (!entry) return;
    setForm({
      location_name: entry.name,
      address: entry.address ?? "",
      parking_notes: entry.parking_notes ?? "",
      parking_address: entry.parking_address ?? "",
      additional_notes: entry.additional_notes ?? "",
    });
    setSaved(false);
  }

  async function autoAddToRoster(name: string, fields: Omit<RosterEntry, "id" | "name">) {
    if (!name) return;
    const alreadyExists = roster.some((r) => r.name.toLowerCase() === name.toLowerCase());
    if (alreadyExists) return;
    try {
      const entry = await api.post<RosterEntry>("/api/location-roster", { name, ...fields });
      setRoster((prev) => [...prev, entry].sort((a, b) => a.name.localeCompare(b.name)));
    } catch (err) { console.error(err); }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setSaved(false); setError("");
    try {
      await api.put(`/api/projects/${id}/location`, form);
      setSaved(true);
      showToast("Location saved");
      autoAddToRoster(form.location_name || form.address, {
        address: form.address || null,
        parking_notes: form.parking_notes || null,
        parking_address: form.parking_address || null,
        additional_notes: form.additional_notes || null,
      });
      if (form.address) setCanContinue(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally { setSaving(false); }
  }

  async function handleAddMove(e: React.FormEvent) {
    e.preventDefault();
    setMoveSaving(true); setMoveError("");
    try {
      const move = await api.post<CompanyMove>(`/api/projects/${id}/company-moves`, {
        label: moveForm.label || null, location_name: moveForm.location_name || null,
        address: moveForm.address || null, parking_notes: moveForm.parking_notes || null,
        parking_address: moveForm.parking_address || null, additional_notes: moveForm.additional_notes || null,
        move_time: moveForm.move_time || null, sort_order: moves.length,
      });
      setMoves((prev) => [...prev, move]);
      setMoveForm(emptyMoveForm);
      showToast("Company move added");
      autoAddToRoster(moveForm.location_name || moveForm.label, {
        address: moveForm.address || null,
        parking_notes: moveForm.parking_notes || null,
        parking_address: moveForm.parking_address || null,
        additional_notes: moveForm.additional_notes || null,
      });
    } catch (err) {
      setMoveError(err instanceof Error ? err.message : "Failed to add");
    } finally { setMoveSaving(false); }
  }

  function startEditMove(move: CompanyMove) {
    setEditingMoveId(move.id);
    setEditMoveForm({ label: move.label ?? "", location_name: move.location_name ?? "", address: move.address ?? "", parking_notes: move.parking_notes ?? "", parking_address: move.parking_address ?? "", additional_notes: move.additional_notes ?? "", move_time: move.move_time ? fmt(move.move_time) : "" });
  }

  async function handleSaveMove(moveId: string) {
    setEditMoveSaving(true);
    try {
      const updated = await api.put<CompanyMove>(`/api/projects/${id}/company-moves/${moveId}`, {
        label: editMoveForm.label || null, location_name: editMoveForm.location_name || null,
        address: editMoveForm.address || null, parking_notes: editMoveForm.parking_notes || null,
        parking_address: editMoveForm.parking_address || null, additional_notes: editMoveForm.additional_notes || null,
        move_time: editMoveForm.move_time || null,
      });
      setMoves((prev) => prev.map((m) => m.id === moveId ? updated : m)); setEditingMoveId(null);
      showToast("Changes saved");
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to save move"); }
    finally { setEditMoveSaving(false); }
  }

  async function handleDeleteMove(moveId: string) {
    await api.delete(`/api/projects/${id}/company-moves/${moveId}`);
    setMoves((prev) => prev.filter((m) => m.id !== moveId));
  }

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10 space-y-10">
      {toastNode}
      {/* Primary location */}
      <div>
        <div className="flex items-start justify-between mb-6">
          <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Primary Location</h2>
          <a href="/location-roster" className="text-xs" style={{ color: "var(--text-muted)" }}>Manage locations →</a>
        </div>
        <div className="card p-5">
          {roster.length > 0 && (
            <div className="mb-5 pb-5" style={{ borderBottom: "1px solid var(--border)" }}>
              <label className="field-label">Fill from saved locations</label>
              <select
                aria-label="Fill from saved locations"
                defaultValue=""
                onChange={(e) => { if (e.target.value) fillFromRoster(e.target.value); e.target.value = ""; }}
                className="field-input"
              >
                <option value="" disabled>Choose a saved location…</option>
                {roster.map((r) => (
                  <option key={r.id} value={r.id}>{r.name}{r.address ? ` — ${r.address}` : ""}</option>
                ))}
              </select>
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div><label className="field-label">Location name</label><input aria-label="Location name" value={form.location_name} onChange={(e) => setForm((p) => ({ ...p, location_name: e.target.value }))} placeholder="Studio A, Rooftop, etc." className="field-input" /></div>
            <div><label className="field-label">Address</label><input aria-label="Address" value={form.address} onChange={(e) => setForm((p) => ({ ...p, address: e.target.value }))} placeholder="123 Main St, Los Angeles, CA" className="field-input" /></div>
            <div><label className="field-label">Parking instructions</label><textarea aria-label="Parking instructions" rows={3} value={form.parking_notes} onChange={(e) => setForm((p) => ({ ...p, parking_notes: e.target.value }))} placeholder="Park in the structure on 5th, validated at reception" className="field-input resize-none" /></div>
            <div><label className="field-label">Parking address <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(if different from location)</span></label><input aria-label="Parking address" value={form.parking_address} onChange={(e) => setForm((p) => ({ ...p, parking_address: e.target.value }))} placeholder="456 Parking Garage Rd, Los Angeles, CA" className="field-input" /></div>
            <div><label className="field-label">Additional notes</label><textarea aria-label="Additional notes" rows={3} value={form.additional_notes} onChange={(e) => setForm((p) => ({ ...p, additional_notes: e.target.value }))} placeholder="Check in at the front desk, bring ID" className="field-input resize-none" /></div>
            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            {saved && <p className="text-xs" style={{ color: "var(--success)" }}>Saved.</p>}
            <button type="submit" disabled={saving} className="btn btn-primary w-full">{saving ? "Saving…" : "Save location"}</button>
          </form>
        </div>
      </div>

      {/* Company moves */}
      <div>
        <div className="flex items-start justify-between mb-6">
          <div>
            <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Company Moves</h2>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Additional locations during the shoot day</p>
          </div>
          <button onClick={() => setShowMoveForm(!showMoveForm)} className="btn btn-primary shrink-0">
            {showMoveForm ? "Done" : "Add move"}
          </button>
        </div>

        {showMoveForm && (
          <form onSubmit={handleAddMove} className="card p-5 mb-6 space-y-4">
            <MoveFields values={moveForm} onChange={(key, val) => setMoveForm((p) => ({ ...p, [key]: val }))} />
            {moveError && <p className="text-xs" style={{ color: "var(--danger)" }}>{moveError}</p>}
            <button type="submit" disabled={moveSaving} className="btn btn-primary">{moveSaving ? "Adding…" : "Add"}</button>
          </form>
        )}

        {moves.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No company moves yet.</p>
        ) : (
          <div className="space-y-3">
            {moves.map((move, idx) =>
              editingMoveId === move.id ? (
                <div key={move.id} className="card p-5 space-y-4">
                  <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Company Move {idx + 1}</p>
                  <MoveFields values={editMoveForm} onChange={(key, val) => setEditMoveForm((p) => ({ ...p, [key]: val }))} />
                  <div className="flex gap-3">
                    <button onClick={() => handleSaveMove(move.id)} disabled={editMoveSaving} className="btn btn-primary">{editMoveSaving ? "Saving…" : "Save"}</button>
                    <button onClick={() => setEditingMoveId(null)} className="btn btn-ghost">Cancel</button>
                  </div>
                </div>
              ) : (
                <div key={move.id} className="card px-5 py-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--text-muted)" }}>
                        Company Move {idx + 1}{move.move_time && ` · ${fmt(move.move_time)}`}
                      </p>
                      {move.label && <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{move.label}</p>}
                      {move.location_name && <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{move.location_name}</p>}
                      {move.address && <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{move.address}</p>}
                      {move.parking_notes && <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Parking: {move.parking_notes}</p>}
                      {move.parking_address && <p className="text-xs" style={{ color: "var(--text-muted)" }}>{move.parking_address}</p>}
                      {move.additional_notes && <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{move.additional_notes}</p>}
                    </div>
                    <div className="flex gap-2 ml-4 shrink-0">
                      <button onClick={() => startEditMove(move)} className="btn btn-ghost btn-sm">Edit</button>
                      <button onClick={() => handleDeleteMove(move.id)} className="btn btn-danger btn-sm">Remove</button>
                    </div>
                  </div>
                </div>
              )
            )}
          </div>
        )}
      </div>

      {/* Advance once the location is set — company moves are captured above first */}
      {canContinue && (
        <div className="flex justify-end pt-2" style={{ borderTop: "1px solid var(--border)" }}>
          <button onClick={() => router.push(`/projects/${id}/schedule`)} className="btn btn-primary">
            Continue to Schedule →
          </button>
        </div>
      )}
    </div>
  );
}
