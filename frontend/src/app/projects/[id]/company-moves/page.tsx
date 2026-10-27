"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { fmt } from "@/lib/time";
import { TimeInput } from "@/components/TimeInput";
import { CardListSkeleton } from "@/components/Skeleton";

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

interface FormFields {
  label: string;
  location_name: string;
  address: string;
  parking_notes: string;
  parking_address: string;
  additional_notes: string;
  move_time: string;
}

const BLANK: FormFields = {
  label: "",
  location_name: "",
  address: "",
  parking_notes: "",
  parking_address: "",
  additional_notes: "",
  move_time: "",
};

function MoveForm({ fields, onChange, onSubmit, onCancel, submitLabel, busy }: {
  fields: FormFields;
  onChange: (k: keyof FormFields, v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  submitLabel: string;
  busy: boolean;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">Label</label>
          <input aria-label="Label" value={fields.label} onChange={(e) => onChange("label", e.target.value)} placeholder="e.g. Move to lunch" className="field-input" />
        </div>
        <div>
          <label className="field-label">Move time</label>
          <TimeInput value={fields.move_time} onChange={(v) => onChange("move_time", v)} />
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">Location name</label>
          <input aria-label="Location name" value={fields.location_name} onChange={(e) => onChange("location_name", e.target.value)} placeholder="e.g. Stage B" className="field-input" />
        </div>
        <div>
          <label className="field-label">Address</label>
          <input aria-label="Address" value={fields.address} onChange={(e) => onChange("address", e.target.value)} placeholder="123 Main St" className="field-input" />
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">Parking address</label>
          <input aria-label="Parking address" value={fields.parking_address} onChange={(e) => onChange("parking_address", e.target.value)} className="field-input" />
        </div>
        <div>
          <label className="field-label">Parking notes</label>
          <input aria-label="Parking notes" value={fields.parking_notes} onChange={(e) => onChange("parking_notes", e.target.value)} placeholder="e.g. Street parking on Oak Ave" className="field-input" />
        </div>
      </div>
      <div>
        <label className="field-label">Additional notes</label>
        <textarea
          aria-label="Additional notes"
          value={fields.additional_notes}
          onChange={(e) => onChange("additional_notes", e.target.value)}
          rows={2}
          className="field-input resize-none"
        />
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="btn btn-primary">{busy ? "Saving…" : submitLabel}</button>
        <button type="button" onClick={onCancel} className="btn btn-ghost">Cancel</button>
      </div>
    </form>
  );
}

export default function CompanyMovesPage() {
  const { id } = useParams<{ id: string }>();
  // Cached by URL — a revisit within the session shows the last-known list
  // instantly instead of blanking to a skeleton again.
  const { data: moves = [], isLoading: loading, mutate: mutateMoves } =
    useSWR<CompanyMove[]>(`/api/projects/${id}/company-moves`, api.get);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormFields>(BLANK);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<FormFields>(BLANK);
  const [editSaving, setEditSaving] = useState(false);

  function setF(field: keyof FormFields, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function setE(field: keyof FormFields, value: string) {
    setEditFields((f) => ({ ...f, [field]: value }));
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError("");
    try {
      const move = await api.post<CompanyMove>(`/api/projects/${id}/company-moves`, {
        label: form.label || null,
        location_name: form.location_name || null,
        address: form.address || null,
        parking_notes: form.parking_notes || null,
        parking_address: form.parking_address || null,
        additional_notes: form.additional_notes || null,
        move_time: form.move_time || null,
        sort_order: moves.length,
      });
      mutateMoves((prev) => [...(prev ?? []), move], false);
      setForm(BLANK);
      setShowForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add move");
    } finally { setSaving(false); }
  }

  function startEdit(move: CompanyMove) {
    setEditingId(move.id);
    setEditFields({
      label: move.label ?? "",
      location_name: move.location_name ?? "",
      address: move.address ?? "",
      parking_notes: move.parking_notes ?? "",
      parking_address: move.parking_address ?? "",
      additional_notes: move.additional_notes ?? "",
      move_time: move.move_time ? fmt(move.move_time) : "",
    });
  }

  async function handleSave(moveId: string) {
    setEditSaving(true); setError("");
    try {
      const updated = await api.put<CompanyMove>(`/api/projects/${id}/company-moves/${moveId}`, {
        label: editFields.label || null,
        location_name: editFields.location_name || null,
        address: editFields.address || null,
        parking_notes: editFields.parking_notes || null,
        parking_address: editFields.parking_address || null,
        additional_notes: editFields.additional_notes || null,
        move_time: editFields.move_time || null,
      });
      mutateMoves((prev) => prev?.map((m) => m.id === moveId ? updated : m), false);
      setEditingId(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to save move"); }
    finally { setEditSaving(false); }
  }

  async function handleRemove(moveId: string) {
    await api.delete(`/api/projects/${id}/company-moves/${moveId}`);
    mutateMoves((prev) => prev?.filter((m) => m.id !== moveId), false);
  }

  return (
    <div className="max-w-2xl mx-auto px-4 md:px-8 py-10">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Company Moves</h2>
        {!showForm && (
          <button onClick={() => setShowForm(true)} className="btn btn-primary">Add move</button>
        )}
      </div>

      {showForm && (
        <div className="card p-5 mb-6">
          <MoveForm
            fields={form}
            onChange={setF}
            onSubmit={handleAdd}
            onCancel={() => { setShowForm(false); setForm(BLANK); setError(""); }}
            submitLabel="Add move"
            busy={saving}
          />
          {error && <p className="text-xs mt-2" style={{ color: "var(--danger)" }}>{error}</p>}
        </div>
      )}

      {loading ? (
        <CardListSkeleton rows={2} />
      ) : moves.length === 0 ? (
        <div className="card p-10 text-center">
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            No company moves yet. Add a move to track location changes during the shoot day.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {moves.map((move, i) => (
            <div key={move.id} className="card overflow-hidden">
              {editingId === move.id ? (
                <div className="p-5">
                  <MoveForm
                    fields={editFields}
                    onChange={setE}
                    onSubmit={(e) => { e.preventDefault(); handleSave(move.id); }}
                    onCancel={() => setEditingId(null)}
                    submitLabel="Save"
                    busy={editSaving}
                  />
                </div>
              ) : (
                <div className="px-5 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-4 min-w-0">
                      {/* Move number */}
                      <div
                        className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 mt-0.5"
                        style={{ background: "var(--accent)", color: "#fff" }}
                      >
                        {i + 1}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          {move.label && (
                            <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                              {move.label}
                            </p>
                          )}
                          {move.move_time && (
                            <span className="text-xs font-medium tabular-nums" style={{ color: "var(--accent-hover)" }}>
                              {fmt(move.move_time)}
                            </span>
                          )}
                        </div>
                        {move.location_name && (
                          <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>{move.location_name}</p>
                        )}
                        {move.address && (
                          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{move.address}</p>
                        )}
                        {(move.parking_address || move.parking_notes) && (
                          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                            Parking: {[move.parking_address, move.parking_notes].filter(Boolean).join(" — ")}
                          </p>
                        )}
                        {move.additional_notes && (
                          <p className="text-xs mt-1 italic" style={{ color: "var(--text-muted)" }}>{move.additional_notes}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      <button onClick={() => startEdit(move)} className="btn btn-ghost btn-sm">Edit</button>
                      <button onClick={() => handleRemove(move.id)} className="btn btn-danger btn-sm">Remove</button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
