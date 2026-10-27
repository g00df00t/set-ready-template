"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { timeToMins, minsToTime, fmt, timeErrorFor } from "@/lib/time";
import { TimeInput } from "@/components/TimeInput";
import { useToast } from "@/components/Toast";
import { CardListSkeleton } from "@/components/Skeleton";

interface ScheduleItem {
  id: string;
  start_time: string;
  end_time: string | null;
  description: string;
  sort_order: number;
}

interface EditFields {
  start_time: string;
  end_time: string;
  description: string;
}

function deltaLabel(mins: number) {
  const abs = Math.abs(mins);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  const sign = mins < 0 ? "−" : "+";
  if (h && m) return `${sign}${h}h ${m}m`;
  if (h) return `${sign}${h}h`;
  return `${sign}${m}m`;
}

const NO_TIME_ERRORS: { start: string | null; end: string | null } = { start: null, end: null };

export default function SchedulePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  // Cached by URL — a revisit within the session shows the last-known list
  // instantly instead of blanking to a skeleton again.
  const { data: items = [], isLoading: loading, mutate: mutateItems } =
    useSWR<ScheduleItem[]>(`/api/projects/${id}/schedule`, api.get);
  // Whether this project's schedule was empty the moment it first loaded —
  // read once below to decide whether "Continue to Call Sheet" appears after
  // adding the first item. Distinct from `items.length === 0`, which would
  // also be true (and wrongly show the button) after removing the only one.
  const wasEmpty = useRef<boolean | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Which of the two time fields the API refused, so only the mistyped one is
  // marked. NO_TIME_ERRORS is a shared frozen literal, not a fresh object per
  // reset, so a clear never counts as a state change.
  const [timeErrors, setTimeErrors] = useState(NO_TIME_ERRORS);
  const [editTimeErrors, setEditTimeErrors] = useState(NO_TIME_ERRORS);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<EditFields>({ start_time: "", end_time: "", description: "" });
  const [originalStartTime, setOriginalStartTime] = useState("");
  const [shiftLater, setShiftLater] = useState(true);
  const [editSaving, setEditSaving] = useState(false);
  const [shifting, setShifting] = useState(false);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  // First time through this project (no items yet, nothing cached): open the
  // add form immediately, and record whether it started empty for wasEmpty
  // above. Guarded to fire once — otherwise removing the last item later
  // would reopen this form and re-arm the "Continue to Call Sheet" button.
  const autoOpenedForm = useRef(false);
  useEffect(() => {
    if (!loading && !autoOpenedForm.current) {
      autoOpenedForm.current = true;
      wasEmpty.current = items.length === 0;
      if (items.length === 0) setShowForm(true);
    }
  }, [loading, items.length]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError(""); setTimeErrors(NO_TIME_ERRORS);
    try {
      const item = await api.post<ScheduleItem>(`/api/projects/${id}/schedule`, {
        start_time: startTime, end_time: endTime || null, description, sort_order: items.length,
      });
      mutateItems((prev) => [...(prev ?? []), item], false);
      setStartTime(""); setEndTime(""); setDescription("");
      showToast("Schedule item added");
    } catch (err) {
      const onFields = { start: timeErrorFor(err, startTime), end: timeErrorFor(err, endTime) };
      setTimeErrors(onFields);
      // Only fall back to the form-level message when neither field owns this.
      const claimed = onFields.start ?? onFields.end;
      setError(claimed ? "" : err instanceof Error ? err.message : "Failed to add item");
    } finally { setSaving(false); }
  }

  function startEdit(item: ScheduleItem) {
    setEditTimeErrors(NO_TIME_ERRORS);
    setEditingId(item.id); setOriginalStartTime(fmt(item.start_time)); setShiftLater(true);
    setEditFields({ start_time: fmt(item.start_time), end_time: item.end_time ? fmt(item.end_time) : "", description: item.description });
  }

  async function handleSaveEdit(item: ScheduleItem) {
    setEditSaving(true); setEditTimeErrors(NO_TIME_ERRORS);
    try {
      const updated = await api.put<ScheduleItem>(`/api/projects/${id}/schedule/${item.id}`, {
        start_time: editFields.start_time, end_time: editFields.end_time || null, description: editFields.description,
      });
      let next = items.map((i) => i.id === item.id ? updated : i);
      const delta = timeToMins(editFields.start_time) - timeToMins(originalStartTime);
      if (!isNaN(delta) && delta !== 0 && shiftLater) {
        const laterItems = items.filter((i) => i.sort_order > item.sort_order);
        const shifted = await Promise.all(laterItems.map((i) => api.put<ScheduleItem>(`/api/projects/${id}/schedule/${i.id}`, {
          start_time: minsToTime(timeToMins(i.start_time) + delta),
          end_time: i.end_time ? minsToTime(timeToMins(i.end_time) + delta) : null,
        })));
        const shiftedMap = Object.fromEntries(shifted.map((s) => [s.id, s]));
        next = next.map((i) => shiftedMap[i.id] ?? i);
      }
      mutateItems(next, false); setEditingId(null);
      showToast("Changes saved");
    } catch (err) {
      const onFields = { start: timeErrorFor(err, editFields.start_time), end: timeErrorFor(err, editFields.end_time) };
      setEditTimeErrors(onFields);
      if (!(onFields.start ?? onFields.end)) showToast(err instanceof Error ? err.message : "Failed to save changes");
    } finally { setEditSaving(false); }
  }

  async function handleDelete(itemId: string) {
    await api.delete(`/api/projects/${id}/schedule/${itemId}`);
    mutateItems((prev) => prev?.filter((i) => i.id !== itemId), false);
  }

  async function shiftAll(deltaMins: number) {
    const shiftable = items.filter((item) => !isNaN(timeToMins(item.start_time)));
    if (!shiftable.length) return;
    setShifting(true);
    try {
      const updated = await Promise.all(shiftable.map((item) => api.put<ScheduleItem>(`/api/projects/${id}/schedule/${item.id}`, {
        start_time: minsToTime(timeToMins(item.start_time) + deltaMins),
        end_time: item.end_time && !isNaN(timeToMins(item.end_time)) ? minsToTime(timeToMins(item.end_time) + deltaMins) : item.end_time ?? null,
      })));
      mutateItems((prev) => prev?.map((item) => updated.find((u) => u.id === item.id) ?? item), false);
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to shift schedule"); }
    finally { setShifting(false); }
  }

  async function handleDrop(toIdx: number) {
    if (dragIndex === null || dragIndex === toIdx) { setDragIndex(null); setDragOverIndex(null); return; }
    const reordered = [...items];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(toIdx, 0, moved);
    const withNewOrders = reordered.map((item, i) => ({ ...item, sort_order: i }));
    mutateItems(withNewOrders, false); setDragIndex(null); setDragOverIndex(null);
    await Promise.all(withNewOrders.map((item) => api.put(`/api/projects/${id}/schedule/${item.id}`, { sort_order: item.sort_order })));
  }

  const editDelta = editFields.start_time && originalStartTime
    ? timeToMins(editFields.start_time) - timeToMins(originalStartTime) : 0;

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10">
      {toastNode}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Schedule</h2>
        <div className="flex gap-2">
          {items.length > 0 && wasEmpty.current && (
            <button onClick={() => router.push(`/projects/${id}/call-sheet`)} className="btn btn-secondary">
              Continue to Call Sheet →
            </button>
          )}
          <button onClick={() => setShowForm(!showForm)} className="btn btn-primary">
            {showForm ? "Done" : "Add item"}
          </button>
        </div>
      </div>

      {/* Shift bar */}
      {items.length > 0 && (
        <div className="card px-5 py-3 mb-6 flex items-center gap-3 flex-wrap">
          <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>Shift entire day:</span>
          {([-60, -30, -15, 15, 30, 60] as const).map((d) => (
            <button key={d} onClick={() => shiftAll(d)} disabled={shifting}
              className="btn btn-secondary btn-sm tabular-nums">
              {d < 0 ? `−${Math.abs(d)}m` : `+${d}m`}
            </button>
          ))}
          {shifting && <span className="text-xs" style={{ color: "var(--text-muted)" }}>Updating…</span>}
        </div>
      )}

      {showForm && (
        <form onSubmit={handleAdd} className="card p-5 mb-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div><label className="field-label">Start time</label><TimeInput value={startTime} onChange={(v) => { setStartTime(v); setTimeErrors(NO_TIME_ERRORS); }} error={timeErrors.start} /></div>
            <div><label className="field-label">End time</label><TimeInput value={endTime} onChange={(v) => { setEndTime(v); setTimeErrors(NO_TIME_ERRORS); }} error={timeErrors.end} /></div>
          </div>
          <div><label className="field-label">Description</label><input required aria-label="Description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Talent arrives, lunch, wrap…" className="field-input" /></div>
          {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
          <button type="submit" disabled={saving} className="btn btn-primary">{saving ? "Adding…" : "Add"}</button>
        </form>
      )}

      {loading ? (
        <CardListSkeleton />
      ) : items.length === 0 && !showForm ? (
        <div className="card p-10 text-center space-y-3">
          <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>No schedule items yet.</p>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>Add the day's key moments — talent arrivals, lunch, company moves, and wrap.</p>
          <button onClick={() => setShowForm(true)} className="btn btn-primary">Add first item</button>
        </div>
      ) : (
        <ol className="space-y-2">
          {items.map((item, idx) =>
            editingId === item.id ? (
              <li key={item.id} className="card p-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="field-label">Start time</label><TimeInput value={editFields.start_time} onChange={(v) => { setEditFields((f) => ({ ...f, start_time: v })); setEditTimeErrors(NO_TIME_ERRORS); }} error={editTimeErrors.start} /></div>
                  <div><label className="field-label">End time</label><TimeInput value={editFields.end_time} onChange={(v) => { setEditFields((f) => ({ ...f, end_time: v })); setEditTimeErrors(NO_TIME_ERRORS); }} error={editTimeErrors.end} /></div>
                </div>
                <div><label className="field-label">Description</label><input aria-label="Description" value={editFields.description} onChange={(e) => setEditFields((f) => ({ ...f, description: e.target.value }))} className="field-input" /></div>
                {editDelta !== 0 && items.some((i) => i.sort_order > item.sort_order) && (
                  <label className="flex items-center gap-2 cursor-pointer select-none rounded-lg px-3 py-2" style={{ background: "var(--accent-subtle)", border: "1px solid var(--accent)" }}>
                    <input type="checkbox" checked={shiftLater} onChange={(e) => setShiftLater(e.target.checked)} className="rounded" />
                    <span className="text-xs" style={{ color: "var(--accent-hover)" }}>
                      Shift all later items {editDelta < 0 ? "earlier" : "later"} by <strong>{deltaLabel(editDelta)}</strong>
                    </span>
                  </label>
                )}
                <div className="flex gap-3">
                  <button onClick={() => handleSaveEdit(item)} disabled={editSaving} className="btn btn-primary btn-sm">{editSaving ? "Saving…" : "Save"}</button>
                  <button onClick={() => setEditingId(null)} className="btn btn-ghost btn-sm">Cancel</button>
                </div>
              </li>
            ) : (
              <li
                key={item.id}
                draggable
                onDragStart={() => setDragIndex(idx)}
                onDragOver={(e) => { e.preventDefault(); if (dragOverIndex !== idx) setDragOverIndex(idx); }}
                onDrop={() => handleDrop(idx)}
                onDragEnd={() => { setDragIndex(null); setDragOverIndex(null); }}
                className="card px-4 py-3 flex items-center gap-3 transition-all"
                style={{
                  opacity: dragIndex === idx ? 0.4 : 1,
                  borderColor: dragOverIndex === idx && dragIndex !== idx ? "var(--accent)" : "var(--border)",
                }}
              >
                <span className="cursor-grab select-none text-base" style={{ color: "var(--text-muted)" }}>⠿</span>
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-semibold tabular-nums" style={{ color: "var(--text-primary)" }}>
                    {fmt(item.start_time)}{item.end_time ? ` – ${fmt(item.end_time)}` : ""}
                  </span>
                  <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>{item.description}</p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button onClick={() => startEdit(item)} className="btn btn-ghost btn-sm">Edit</button>
                  <button onClick={() => handleDelete(item.id)} className="btn btn-danger btn-sm">Remove</button>
                </div>
              </li>
            )
          )}
        </ol>
      )}
    </div>
  );
}
