"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import AppFooter from "@/components/AppFooter";
import { CardListSkeleton } from "@/components/Skeleton";

interface LocationEntry {
  id: string;
  name: string;
  address: string | null;
  parking_notes: string | null;
  parking_address: string | null;
  additional_notes: string | null;
}

interface EditFields {
  name: string;
  address: string;
  parking_notes: string;
  parking_address: string;
  additional_notes: string;
}

const BLANK: EditFields = { name: "", address: "", parking_notes: "", parking_address: "", additional_notes: "" };

function LocationForm({ fields, onChange, onSubmit, onCancel, submitLabel, busy }: {
  fields: EditFields;
  onChange: (k: keyof EditFields, v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
  submitLabel: string;
  busy: boolean;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label className="field-label">Location name</label>
        <input required aria-label="Location name" value={fields.name} onChange={(e) => onChange("name", e.target.value)} placeholder="Sony Stage 15, The Factory…" className="field-input" />
      </div>
      <div>
        <label className="field-label">Address</label>
        <input aria-label="Address" value={fields.address} onChange={(e) => onChange("address", e.target.value)} placeholder="123 Main St, Los Angeles, CA" className="field-input" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">Parking address</label>
          <input aria-label="Parking address" value={fields.parking_address} onChange={(e) => onChange("parking_address", e.target.value)} className="field-input" />
        </div>
        <div>
          <label className="field-label">Parking notes</label>
          <input aria-label="Parking notes" value={fields.parking_notes} onChange={(e) => onChange("parking_notes", e.target.value)} placeholder="Lot B, enter on Oak Ave" className="field-input" />
        </div>
      </div>
      <div>
        <label className="field-label">Additional notes</label>
        <textarea aria-label="Additional notes" value={fields.additional_notes} onChange={(e) => onChange("additional_notes", e.target.value)} rows={2} className="field-input resize-none" />
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="btn btn-primary">{busy ? "Saving…" : submitLabel}</button>
        <button type="button" onClick={onCancel} className="btn btn-ghost">Cancel</button>
      </div>
    </form>
  );
}

export default function LocationRosterPage() {
  const router = useRouter();
  // Cached by URL — a revisit within the session shows the last-known list
  // instantly instead of blanking to a skeleton again.
  const { data: locations = [], isLoading: loading, mutate: mutateLocations } =
    useSWR<LocationEntry[]>("/api/location-roster", api.get);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<EditFields>(BLANK);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<EditFields>(BLANK);
  const [editSaving, setEditSaving] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError("");
    try {
      const entry = await api.post<LocationEntry>("/api/location-roster", {
        name: form.name,
        address: form.address || null,
        parking_notes: form.parking_notes || null,
        parking_address: form.parking_address || null,
        additional_notes: form.additional_notes || null,
      });
      mutateLocations((prev) => [...(prev ?? []), entry].sort((a, b) => a.name.localeCompare(b.name)), false);
      setForm(BLANK);
      setShowForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add");
    } finally { setSaving(false); }
  }

  function startEdit(entry: LocationEntry) {
    setEditingId(entry.id);
    setEditFields({
      name: entry.name,
      address: entry.address ?? "",
      parking_notes: entry.parking_notes ?? "",
      parking_address: entry.parking_address ?? "",
      additional_notes: entry.additional_notes ?? "",
    });
  }

  async function handleSave(entryId: string) {
    if (!editFields.name.trim()) { setEditError("A name is required."); return; }
    setEditError(null);
    setEditSaving(true);
    try {
      const updated = await api.put<LocationEntry>(`/api/location-roster/${entryId}`, {
        name: editFields.name,
        address: editFields.address || null,
        parking_notes: editFields.parking_notes || null,
        parking_address: editFields.parking_address || null,
        additional_notes: editFields.additional_notes || null,
      });
      mutateLocations((prev) => prev?.map((e) => e.id === entryId ? updated : e), false);
      setEditingId(null);
    } catch (err) {
      setEditError(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that change.");
    }
    finally { setEditSaving(false); }
  }

  // Asks first, like the Master Roster: the first click turns Remove into
  // "Remove Pier 57?" with a Cancel beside it.
  async function handleRemove(entryId: string) {
    if (confirmRemove !== entryId) { setConfirmRemove(entryId); return; }
    setConfirmRemove(null);
    await api.delete(`/api/location-roster/${entryId}`);
    mutateLocations((prev) => prev?.filter((e) => e.id !== entryId), false);
  }

  const filtered = search.trim()
    ? locations.filter((e) => [e.name, e.address].some((f) => f?.toLowerCase().includes(search.toLowerCase())))
    : locations;

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="px-6 py-3 flex items-center justify-between"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>SET&gt;READY</span>
        <button onClick={() => router.back()} className="text-xs" style={{ color: "var(--text-secondary)" }}>← Back</button>
      </header>

      <main className="flex-1 w-full max-w-3xl mx-auto px-4 md:px-6 py-10">
        {editError && (
          <div className="card px-4 py-3 mb-6 flex items-start justify-between gap-4" role="alert"
            style={{ borderColor: "var(--danger)" }}>
            <span className="text-sm" style={{ color: "var(--danger)" }}>{editError}</span>
            <button onClick={() => setEditError(null)} className="text-xs"
              style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }} aria-label="Dismiss">
              Dismiss
            </button>
          </div>
        )}
        <div className="flex items-start justify-between mb-8">
          <div>
            <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Locations</h2>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Saved locations you can pull into any project</p>
          </div>
          <button onClick={() => setShowForm(!showForm)} className="btn btn-primary shrink-0">
            {showForm ? "Done" : "Add location"}
          </button>
        </div>

        {showForm && (
          <div className="card p-5 mb-6">
            <LocationForm
              fields={form}
              onChange={(k, v) => setForm((f) => ({ ...f, [k]: v }))}
              onSubmit={handleAdd}
              onCancel={() => { setShowForm(false); setForm(BLANK); setError(""); }}
              submitLabel="Add location"
              busy={saving}
            />
            {error && <p className="text-xs mt-2" style={{ color: "var(--danger)" }}>{error}</p>}
          </div>
        )}

        {locations.length > 4 && (
          <div className="mb-4">
            <input aria-label="Search locations" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search locations…" className="field-input" />
          </div>
        )}

        {loading ? (
          <CardListSkeleton rows={2} />
        ) : locations.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No saved locations yet. Add studios, stages, or venues you use regularly.</p>
        ) : filtered.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No matches for &ldquo;{search}&rdquo;.</p>
        ) : (
          <div className="space-y-3">
            {filtered.map((entry) => (
              <div key={entry.id} className="card overflow-hidden">
                {editingId === entry.id ? (
                  <div className="p-5">
                    <LocationForm
                      fields={editFields}
                      onChange={(k, v) => setEditFields((f) => ({ ...f, [k]: v }))}
                      onSubmit={(e) => { e.preventDefault(); handleSave(entry.id); }}
                      onCancel={() => setEditingId(null)}
                      submitLabel="Save"
                      busy={editSaving}
                    />
                  </div>
                ) : (
                  <div className="flex items-start justify-between px-5 py-4 gap-4">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{entry.name}</p>
                      {entry.address && <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{entry.address}</p>}
                      {(entry.parking_address || entry.parking_notes) && (
                        <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                          Parking: {[entry.parking_address, entry.parking_notes].filter(Boolean).join(" — ")}
                        </p>
                      )}
                      {entry.additional_notes && (
                        <p className="text-xs mt-1 italic" style={{ color: "var(--text-muted)" }}>{entry.additional_notes}</p>
                      )}
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      <button onClick={() => startEdit(entry)} className="btn btn-ghost btn-sm">Edit</button>
                      {confirmRemove === entry.id ? (
                        <>
                          <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm">Remove {entry.name}?</button>
                          <button onClick={() => setConfirmRemove(null)} className="btn btn-ghost btn-sm">Cancel</button>
                        </>
                      ) : (
                        <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm">Remove</button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
      <AppFooter />
    </div>
  );
}
