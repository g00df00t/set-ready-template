"use client";

// /account's Job defaults: what every new job's per diem starts as. Each job
// can change its own on Pre-production; jobs already set up keep theirs.
// Account-wide, so on a shared account it's the owner's (backend
// routers/account.py, GET/PUT /account/job-defaults).

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cleanAmount, num } from "@/lib/rates";

interface Defaults { per_diem_shoot: number | null; per_diem_other: number | null; per_diem_paid_by: string | null }

export function JobDefaultsCard() {
  const [shoot, setShoot] = useState("");
  const [other, setOther] = useState("");
  const [paidBy, setPaidBy] = useState("");
  const [loaded, setLoaded] = useState<Defaults | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);

  function show(d: Defaults) {
    setLoaded(d);
    setShoot(num(d.per_diem_shoot)?.toString() ?? "");
    setOther(num(d.per_diem_other)?.toString() ?? "");
    setPaidBy(d.per_diem_paid_by ?? "");
  }

  useEffect(() => {
    api.get<Defaults>("/api/account/job-defaults").then(show)
      .catch(() => setMessage({ text: "Couldn't load your job defaults.", error: true }));
  }, []);

  const dirty = loaded !== null && (
    shoot !== (num(loaded.per_diem_shoot)?.toString() ?? "")
    || other !== (num(loaded.per_diem_other)?.toString() ?? "")
    || paidBy !== (loaded.per_diem_paid_by ?? ""));

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      show(await api.put<Defaults>("/api/account/job-defaults", {
        per_diem_shoot: shoot === "" ? null : Number(shoot),
        per_diem_other: other === "" ? null : Number(other),
        per_diem_paid_by: paidBy.trim() || null,
      }));
      setMessage({ text: "Saved. New jobs start with these." });
    } catch (err) {
      setMessage({ text: err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save.", error: true });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card p-6 mb-6">
      <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Job defaults</h2>
      <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
        Every new job starts with these. Change them on any job&apos;s Pre-production tab; jobs already set up keep what they have.
      </p>
      <p className="field-label">Per diem</p>
      <div className="grid gap-3 grid-cols-2 mb-4">
        {([["def-pd-shoot", "Shoot days", shoot, setShoot], ["def-pd-other", "Non-shoot days", other, setOther]] as const)
          .map(([fid, label, value, set]) => (
            <div key={fid}>
              <label htmlFor={fid} className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</label>
              <div className="flex items-center gap-1.5">
                <span className="date-text" style={{ color: "var(--text-muted)" }}>$</span>
                <input id={fid} inputMode="decimal" value={value} onChange={(e) => set(cleanAmount(e.target.value))} onFocus={(e) => e.currentTarget.select()}
                  className="field-input date-text" />
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>/day</span>
              </div>
            </div>
          ))}
      </div>
      <label htmlFor="def-pd-paid" className="field-label">Per diem paid by</label>
      <input id="def-pd-paid" value={paidBy} onChange={(e) => setPaidBy(e.target.value)}
        placeholder="e.g. Venmo or cash" className="field-input" />
      <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
        Down days are always ½ the shoot day rate, with per diem and a hotel night.
      </p>
      <div className="flex items-center gap-3 mt-4">
        <button onClick={save} disabled={saving || !dirty} className="btn btn-primary">
          {saving ? "Saving…" : "Save defaults"}
        </button>
        {message && (
          <span role={message.error ? "alert" : "status"} className="text-xs"
            style={{ color: message.error ? "var(--danger)" : "var(--text-secondary)" }}>
            {message.text}
          </span>
        )}
      </div>
    </div>
  );
}
