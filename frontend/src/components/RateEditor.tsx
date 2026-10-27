"use client";

// A hire's agreed rates, edited inside the Pre-production table's <Popover>.
// The deal belongs to the hire: it starts as their last job for this client
// (or the Master Roster's rate) and nothing rewrites it afterwards — rates
// change by client, so there's no single "their rate" to send back to the
// Roster (docs/producer-documents-map.md §3, the producer 2026-10-01).

import { useState } from "react";
import { DayTypeTag } from "@/components/DayType";
import {
  PrepMode, RateSuggestion, Rates, cleanAmount, money, num, prepFor, prepModeOf,
} from "@/lib/rates";

export interface RateSave extends Rates {
  rate_source?: "job" | "roster";
  rate_source_job_id?: string | null;
}

function AmountField({ id, label, value, onChange, disabled }: {
  id: string; label: React.ReactNode; value: string; onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <div>
      <label htmlFor={id} className="field-label">{label}</label>
      <div className="flex items-center gap-1.5">
        <span className="date-text" style={{ color: "var(--text-muted)" }}>$</span>
        <input
          id={id}
          inputMode="decimal"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(cleanAmount(e.target.value))}
          placeholder="Not set"
          className="field-input date-text"
        />
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>/day</span>
      </div>
    </div>
  );
}

export function RateEditor({ name, clientName, rates, suggestion, source, onSave, onCancel }: {
  name: string;
  clientName: string | null;
  rates: Rates;
  // Offered when the hire has no rates yet; saving it records where it came from.
  suggestion: RateSuggestion | null;
  // Where saved rates came from, for the line at the top.
  source: { kind: "job" | "roster" | null; jobName: string | null };
  onSave: (r: RateSave) => Promise<void>;
  onCancel: () => void;
}) {
  const start: Rates = suggestion ?? rates;
  const [shoot, setShoot] = useState(num(start.rate_shoot)?.toString() ?? "");
  const [travel, setTravel] = useState(num(start.rate_travel)?.toString() ?? "");
  const [mode, setMode] = useState<PrepMode>(prepModeOf(num(start.rate_shoot), num(start.rate_prep)));
  const [customPrep, setCustomPrep] = useState(num(start.rate_prep)?.toString() ?? "");
  const [note, setNote] = useState(start.rate_note ?? "");
  const [saving, setSaving] = useState(false);

  const shootN = shoot === "" ? null : Number(shoot);
  const prepN = prepFor(mode, shootN, customPrep === "" ? null : Number(customPrep));
  const first = name.split(" ")[0];
  const from = suggestion ?? (source.kind ? { rate_source: source.kind, rate_source_job_name: source.jobName } : null);
  const client = clientName || "this client";

  async function save() {
    setSaving(true);
    try {
      await onSave({
        rate_shoot: shootN,
        rate_travel: travel === "" ? null : Number(travel),
        rate_prep: prepN,
        rate_note: note.trim() || null,
        ...(suggestion ? { rate_source: suggestion.rate_source, rate_source_job_id: suggestion.rate_source_job_id } : {}),
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); save(); }} className="grid gap-3">
      <div>
        <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Rate · {name}</p>
        {from && (
          <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
            {suggestion ? "Suggested from " : "Filled in from "}
            {from.rate_source === "job"
              ? <>{first}&apos;s last {client} job{from.rate_source_job_name ? <>, {from.rate_source_job_name}</> : null}.</>
              : <>the Master Roster — {first}&apos;s first {client} job.</>}
          </p>
        )}
        <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
          Rates change by client, so this job keeps its own copy.
        </p>
      </div>

      <AmountField id="rate-shoot" label={<DayTypeTag type="shoot" />} value={shoot} onChange={setShoot} />
      <AmountField id="rate-travel" label={<DayTypeTag type="travel" label="Travel day" />} value={travel} onChange={setTravel} />

      <div>
        <div className="flex items-center justify-between gap-2">
          <span className="field-label" id="rate-prep-label"><DayTypeTag type="prep" /></span>
          <span role="group" aria-labelledby="rate-prep-label" className="flex gap-1">
            {(["full", "half", "custom"] as const).map((m) => (
              <button key={m} type="button" aria-pressed={mode === m}
                onClick={() => { setMode(m); if (m === "custom" && customPrep === "" && prepN !== null) setCustomPrep(String(prepN)); }}
                className={`btn btn-sm ${mode === m ? "btn-secondary" : "btn-ghost"}`}>
                {m === "full" ? "Full" : m === "half" ? "½" : "Custom"}
              </button>
            ))}
          </span>
        </div>
        {mode === "custom" ? (
          <AmountField id="rate-prep" label={<span className="sr-only">Prep/Scout day rate</span>} value={customPrep} onChange={setCustomPrep} />
        ) : (
          <p className="date-text text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            {prepN === null ? "Set a shoot rate first" : `${money(prepN)}/day`}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="rate-note" className="field-label">Rate note</label>
        <input id="rate-note" value={note} onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. 10-hour day incl. 30-min meal" className="field-input" />
      </div>

      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        Down day is always ½ the shoot rate. Producer-only: prints on {first}&apos;s deal memo and nowhere else.
      </p>

      <div className="flex items-center gap-2">
        <button type="submit" disabled={saving} className="btn btn-primary btn-sm">{saving ? "Saving…" : "Save rate"}</button>
        <button type="button" onClick={onCancel} className="btn btn-ghost btn-sm">Cancel</button>
      </div>
    </form>
  );
}
