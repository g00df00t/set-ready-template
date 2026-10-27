"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

interface Project {
  id: string;
  notes: string | null;
}

export default function NotesPage() {
  const { id } = useParams<{ id: string }>();
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<"saved" | "unsaved" | "saving" | "">("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialLoad = useRef(true);

  useEffect(() => {
    api.get<Project>(`/api/projects/${id}`)
      .then((p) => { setNotes(p.notes ?? ""); initialLoad.current = false; })
      .catch(console.error);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [id]);

  async function saveNotes(value: string) {
    setStatus("saving");
    await api.put(`/api/projects/${id}`, { notes: value }).catch(console.error);
    setStatus("saved");
    setTimeout(() => setStatus(""), 2000);
  }

  function handleChange(value: string) {
    setNotes(value);
    if (initialLoad.current) return;
    setStatus("unsaved");
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => saveNotes(value), 1500);
  }

  const statusText = status === "unsaved" ? "Unsaved" : status === "saving" ? "Saving…" : status === "saved" ? "Saved" : "";
  const statusColor = status === "unsaved" ? "var(--text-muted)" : status === "saving" ? "var(--text-muted)" : "var(--success)";

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Notes</h2>
        {statusText && <span className="text-xs" style={{ color: statusColor }}>{statusText}</span>}
      </div>
      {/* Private on purpose: services/call_sheet_data.py withholds them. */}
      <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
        Just for you. These notes stay off the call sheet and everything crew see.
      </p>
      <textarea
        value={notes}
        onChange={(e) => handleChange(e.target.value)}
        onBlur={(e) => {
          if (status === "unsaved") {
            if (debounceRef.current) clearTimeout(debounceRef.current);
            saveNotes(e.target.value);
          }
        }}
        rows={16}
        placeholder="Shot list priorities, special instructions, client notes…"
        className="field-input resize-none"
      />
    </div>
  );
}
