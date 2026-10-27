"use client";

// A debounced-autosave text field: type, pause, it saves. Same shape the
// day's Deal Memos page (projects/[id]/deal-memos/page.tsx) built first for
// job details and per-person dates blocks — pulled out here so the job's own
// Pre-production tab (client/production company/payroll provider) doesn't
// carry a third copy. Not wired into the day page, which keeps its own local
// copy: this is Phase 1's shared version for Jobs, not a refactor of code the
// current version depends on.

import { useEffect, useRef, useState } from "react";

export type SaveStatus = "saved" | "unsaved" | "saving" | "";

export function useAutosaveField(initial: string, save: (value: string) => Promise<void>) {
  const [value, setValue] = useState(initial);
  const [status, setStatus] = useState<SaveStatus>("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialLoad = useRef(true);

  useEffect(() => {
    setValue(initial);
    initialLoad.current = true;
    const t = setTimeout(() => { initialLoad.current = false; }, 0);
    return () => clearTimeout(t);
  }, [initial]);

  async function commit(v: string) {
    setStatus("saving");
    await save(v).catch(console.error);
    setStatus("saved");
    setTimeout(() => setStatus(""), 2000);
  }

  function handleChange(v: string) {
    setValue(v);
    if (initialLoad.current) return;
    setStatus("unsaved");
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => commit(v), 1200);
  }

  function handleBlur() {
    if (status === "unsaved") {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      commit(value);
    }
  }

  return { value, status, handleChange, handleBlur };
}

export function SaveStatusDot({ status }: { status: SaveStatus }) {
  if (!status) return null;
  const text = status === "unsaved" ? "Unsaved" : status === "saving" ? "Saving…" : "Saved";
  const color = status === "saved" ? "var(--success)" : "var(--text-muted)";
  return <span className="text-xs" style={{ color }}>{text}</span>;
}
