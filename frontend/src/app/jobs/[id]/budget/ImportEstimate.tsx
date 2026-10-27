"use client";

/* Budget → "Read an estimate": a PDF or Excel estimate in, draft lines out,
 * each with the basis Claude suggests and why (backend routers/estimate_import.py).
 * Nothing goes on the estimate until she adds it; the kept lines go in one
 * request (POST .../budget/lines/batch), all or none.
 *
 * The basis is the point: no estimate says it, and it decides how every line
 * reconciles. So it's shown on every draft, with the reason, and editable.
 *
 * The file isn't kept. The printed grand total is checked against the lines'
 * sum by the API, and a mismatch (a discount, a line that wasn't read) is said
 * plainly rather than smoothed over.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { DateText } from "@/components/DateText";
import { centsToInput, formatCents, parseCents } from "@/lib/money";

type Bucket = "fee" | "rate" | "pass";
interface ReadLine {
  section: string | null; name: string; block: string | null; qty: number | null; unit_amount_cents: number | null;
  est_cents: number; bucket: Bucket; basis_reason: string | null; floor_kind: string | null; markup_bp: number;
}
interface ReadResult {
  lines: ReadLine[]; skipped: number; note: string | null;
  total_check: { stated_cents: number | null; lines_cents: number; matches: boolean | null };
}
interface Draft extends ReadLine { key: string; include: boolean; amount: string }

// Mirrors backend services/estimate_import.py, so a file that's too big is
// refused at once instead of after the upload.
const MAX_BYTES = 15 * 1024 * 1024;
const ACCEPT = ".pdf,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const BASIS: { key: Bucket; label: string }[] = [{ key: "fee", label: "Fee" }, { key: "rate", label: "Fixed" }, { key: "pass", label: "At cost" }];

export function ImportEstimate<V>({ jobId, onAdded, toast }: {
  jobId: string; onAdded: (view: V) => void; toast: (msg: string) => void;
}) {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [result, setResult] = useState<Omit<ReadResult, "lines"> & { fileName: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
    const swallow = (e: DragEvent) => { if (hasFiles(e)) e.preventDefault(); };
    window.addEventListener("dragover", swallow);
    window.addEventListener("drop", swallow);
    return () => { window.removeEventListener("dragover", swallow); window.removeEventListener("drop", swallow); };
  }, []);

  const isFileDrag = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

  async function read(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    if (file.size > MAX_BYTES) { setProblem(`${file.name}: too big — an estimate can be up to 15 MB.`); return; }
    setReading(true);
    try {
      const out = await api.uploadFile<ReadResult>(`/api/jobs/${jobId}/budget/import`, file, file.type || "application/octet-stream");
      if (out.note) setProblem(`${file.name}: ${out.note}`);
      setDrafts(out.lines.map((l, i) => ({ ...l, key: `${i}-${Date.now()}`, include: true, amount: centsToInput(l.est_cents) })));
      setResult({ skipped: out.skipped, note: out.note, total_check: out.total_check, fileName: file.name });
    } catch (err) {
      setProblem(`${file.name}: ${err instanceof Error ? err.message : "Couldn't read it."}`);
    } finally {
      setReading(false);
      setInputKey((k) => k + 1);
    }
  }

  const set = (key: string, patch: Partial<Draft>) => setDrafts((d) => d.map((x) => (x.key === key ? { ...x, ...patch } : x)));

  async function addAll() {
    const chosen = drafts.filter((d) => d.include);
    const bad = chosen.find((d) => { const c = parseCents(d.amount); return !d.name.trim() || c === null || c === undefined; });
    if (bad) { toast(`Check the description and amount on "${bad.name || "a line"}".`); return; }
    setAdding(true);
    try {
      const view = await api.post<V>(`/api/jobs/${jobId}/budget/lines/batch`, {
        lines: chosen.map((d) => {
          const cents = parseCents(d.amount) as number;
          // An amount changed by hand stands alone: a qty × rate beside it would no longer add up.
          const keepQty = cents === d.est_cents;
          return {
            section: d.section?.trim() || null, name: d.name.trim(), block: d.block, bucket: d.bucket,
            qty: keepQty ? d.qty : null, unit_amount_cents: keepQty ? d.unit_amount_cents : null, est_cents: cents,
            floor_kind: d.floor_kind, markup_bp: d.bucket === "pass" ? d.markup_bp : 0,
          };
        }),
      });
      onAdded(view);
      toast(`${chosen.length} ${chosen.length === 1 ? "line" : "lines"} added to the estimate.`);
      setDrafts([]); setResult(null); setProblem(null);
    } catch (err) {
      toast(err instanceof Error ? `Couldn't add them: ${err.message}` : "Couldn't add them.");
    } finally {
      setAdding(false);
    }
  }

  const count = drafts.filter((d) => d.include).length;
  const check = result?.total_check;

  return (
    <section className="card p-4 mb-4 grid gap-3" aria-label="Read an estimate"
      onDragEnter={(e) => { if (!isFileDrag(e)) return; depth.current += 1; setDragging(true); }}
      onDragOver={(e) => { if (!isFileDrag(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = reading ? "none" : "copy"; }}
      onDragLeave={(e) => { if (!isFileDrag(e)) return; depth.current = Math.max(0, depth.current - 1); if (!depth.current) setDragging(false); }}
      onDrop={(e) => {
        if (!isFileDrag(e)) return;
        e.preventDefault();
        depth.current = 0;
        setDragging(false);
        if (!reading) read(e.dataTransfer.files[0]);
      }}>
      <div>
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Read an estimate</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          A PDF or Excel file. Claude drafts its lines and suggests each one&apos;s basis; nothing goes on the estimate until you add it.
        </p>
      </div>
      <div className="rounded-lg p-5 text-center"
        style={{
          border: `2px dashed ${dragging ? "var(--accent)" : "var(--border-strong)"}`,
          background: dragging ? "var(--accent-subtle)" : "var(--bg-inset)",
          transition: "background 120ms, border-color 120ms",
        }}>
        <p className="text-sm" style={{ color: "var(--text-primary)" }} aria-live="polite">
          {reading ? "Reading the estimate…" : dragging ? "Drop to read it" : (
            <>
              Drop the estimate here, or{" "}
              <label className="underline" style={{ color: "var(--accent-text)", cursor: "pointer" }}>
                choose it
                <input key={inputKey} type="file" accept={ACCEPT} className="sr-only" disabled={reading}
                  onChange={(e) => read(e.target.files?.[0])} />
              </label>
            </>
          )}
        </p>
      </div>

      {problem && <p className="text-xs" style={{ color: "var(--warning)" }} role="status">{problem}</p>}

      {drafts.length > 0 && check && (
        <>
          <div className="rounded-md p-3 text-sm grid gap-1" role="status"
            style={{ background: check.matches === false ? "var(--warning-subtle)" : "var(--bg-inset)", color: "var(--text-primary)" }}>
            <p>
              {drafts.length} {drafts.length === 1 ? "line" : "lines"} read from {result.fileName}, coming to{" "}
              <DateText>{formatCents(check.lines_cents)}</DateText>.{" "}
              {check.matches === true && <span style={{ color: "var(--text-secondary)" }}>That matches its printed total.</span>}
              {check.matches === false && (
                <>The estimate&apos;s printed total is <DateText>{formatCents(check.stated_cents)}</DateText>. A discount, or a line that
                  wasn&apos;t read? Check before adding.</>
              )}
              {check.matches === null && <span style={{ color: "var(--text-secondary)" }}>No printed total to check it against.</span>}
            </p>
            {result.skipped > 0 && (
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {result.skipped} {result.skipped === 1 ? "row was" : "rows were"} left out (discounts, TBDs, lines with no amount). Add
                {result.skipped === 1 ? " it" : " them"} by hand if {result.skipped === 1 ? "it belongs" : "they belong"}.
              </p>
            )}
          </div>

          <div className="data-table-raised">
            <table>
              <thead>
                <tr>
                  <th aria-label="Add" />
                  <th>Heading</th>
                  <th style={{ minWidth: "13rem" }}>Description</th>
                  <th style={{ textAlign: "right" }}>Qty × rate</th>
                  <th style={{ textAlign: "right" }}>Amount</th>
                  <th>Basis</th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((d) => (
                  <tr key={d.key} style={{ opacity: d.include ? 1 : 0.5 }}>
                    <td><input type="checkbox" checked={d.include} onChange={(e) => set(d.key, { include: e.target.checked })}
                      aria-label={`Add ${d.name}`} /></td>
                    <td><input value={d.section ?? ""} onChange={(e) => set(d.key, { section: e.target.value })} maxLength={120}
                      placeholder="No heading" aria-label={`Heading for ${d.name}`} className="field-ghost" style={{ minWidth: "8rem" }} /></td>
                    <td>
                      <span className="grid gap-0.5">
                        <input value={d.name} onChange={(e) => set(d.key, { name: e.target.value })} maxLength={200}
                          aria-label="Description" className="field-ghost" />
                        {(d.floor_kind || d.block) && (
                          <span className="flex gap-1.5">
                            {d.floor_kind && <span className="custom-pill">Floor line</span>}
                            {d.block && <span className="custom-pill">{d.block}</span>}
                          </span>
                        )}
                      </span>
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <span style={{ display: "inline-block", padding: "0.375rem 0.5rem", color: "var(--text-secondary)" }}>
                        <DateText>{d.qty !== null && d.unit_amount_cents !== null && parseCents(d.amount) === d.est_cents
                          ? `${d.qty} × ${formatCents(d.unit_amount_cents)}` : "—"}</DateText>
                      </span>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <input value={d.amount} onChange={(e) => set(d.key, { amount: e.target.value })} inputMode="decimal"
                        aria-label={`Amount for ${d.name}`} className="field-ghost date-text" style={{ width: "11ch", textAlign: "right" }} />
                    </td>
                    <td>
                      <span className="grid gap-0.5">
                        <select value={d.bucket} onChange={(e) => set(d.key, { bucket: e.target.value as Bucket })}
                          className="field-ghost" style={{ width: "auto" }} aria-label={`Basis for ${d.name}`}
                          disabled={!!d.floor_kind} title={d.floor_kind ? "A floor line is always a Fee" : undefined}>
                          {BASIS.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
                        </select>
                        {d.basis_reason && <span className="text-xs" style={{ color: "var(--text-muted)", paddingLeft: "0.5rem" }}>{d.basis_reason}</span>}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn btn-primary btn-sm" disabled={adding || !count} onClick={addAll}>
              {adding ? "Adding…" : `Add ${count} ${count === 1 ? "line" : "lines"} to the estimate`}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={adding}
              onClick={() => { setDrafts([]); setResult(null); setProblem(null); }}>Discard</button>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>Check each basis: it decides how the line reconciles.</span>
          </div>
        </>
      )}
    </section>
  );
}
