"use client";

/* PC log → "Read receipts": photos or PDFs in, draft lines out, for the producer
 * to check before any of them goes on the log (backend routers/receipts.py).
 *
 * Drop files anywhere on the card, or choose them (phones have nothing to
 * drag). While the page is open, a file dropped just outside the card is
 * ignored rather than opened by the browser in place of the app.
 *
 * One request per file, in turn, so a batch of thirty shows progress and one
 * bad photo doesn't sink the rest. "These are all…" puts every line in one
 * column — a lunch receipt could be per diem or a client meal, and the paper
 * can't say which; she can. A draft she doesn't keep has its kept file thrown
 * away, unless another draft from the same receipt is being added.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { DateInput } from "@/components/DateInput";
import { centsToInput, parseCents } from "@/lib/money";

interface Receipt { receipt_path: string; receipt_name: string; receipt_type: string }
interface ReadLine { spent_on: string | null; payee: string; description: string; amount_cents: number; category: string }
interface ReadResult { lines: ReadLine[]; receipt: Receipt | null; note: string | null }
interface Draft {
  key: string; fileName: string; receipt: Receipt | null; include: boolean;
  spent_on: string; payee: string; description: string; amount: string; category: string;
}

// Mirrors backend services/receipt_import.py, so a file that's too big is
// refused at once instead of after the upload.
const MAX_BYTES = 15 * 1024 * 1024;
const ACCEPT = "image/jpeg,image/png,image/webp,image/gif,application/pdf";

export function ReadReceipts({ jobId, cats, onAdded, toast }: {
  jobId: string; cats: [string, string][]; onAdded: () => Promise<unknown>; toast: (msg: string) => void;
}) {
  const [category, setCategory] = useState("");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [problems, setProblems] = useState<{ fileName: string; message: string }[]>([]);
  const [reading, setReading] = useState<{ done: number; total: number } | null>(null);
  const [adding, setAdding] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const [dragging, setDragging] = useState(false);
  // dragenter/dragleave fire for every child the pointer crosses; counting
  // them is what keeps the highlight from flickering.
  const depth = useRef(0);

  useEffect(() => {
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
    const swallow = (e: DragEvent) => { if (hasFiles(e)) e.preventDefault(); };
    window.addEventListener("dragover", swallow);
    window.addEventListener("drop", swallow);
    return () => { window.removeEventListener("dragover", swallow); window.removeEventListener("drop", swallow); };
  }, []);

  const isFileDrag = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

  async function read(files: File[]) {
    if (!files.length) return;
    setReading({ done: 0, total: files.length });
    for (const [i, file] of files.entries()) {
      if (file.size > MAX_BYTES) {
        setProblems((p) => [...p, { fileName: file.name, message: "Too big — a receipt can be up to 15 MB." }]);
      } else {
        try {
          const qs = new URLSearchParams({ filename: file.name, ...(category ? { category } : {}) });
          const out = await api.uploadFile<ReadResult>(`/api/jobs/${jobId}/receipts/read?${qs}`, file,
            file.type || "application/octet-stream");
          if (out.note) setProblems((p) => [...p, { fileName: file.name, message: out.note! }]);
          setDrafts((d) => [...d, ...out.lines.map((l, j) => ({
            key: `${file.name}-${i}-${j}-${Date.now()}`, fileName: file.name, receipt: out.receipt, include: true,
            spent_on: l.spent_on ?? "", payee: l.payee, description: l.description,
            amount: centsToInput(l.amount_cents), category: l.category,
          }))]);
        } catch (err) {
          setProblems((p) => [...p, { fileName: file.name, message: err instanceof Error ? err.message : "Couldn't read it." }]);
        }
      }
      setReading({ done: i + 1, total: files.length });
    }
    setReading(null);
    setInputKey((k) => k + 1);
  }

  const set = (key: string, patch: Partial<Draft>) => setDrafts((d) => d.map((x) => (x.key === key ? { ...x, ...patch } : x)));

  /** Files no kept draft points at — thrown away rather than left in the bucket. */
  async function discardFiles(kept: Draft[], dropped: Draft[]) {
    const keep = new Set(kept.map((d) => d.receipt?.receipt_path).filter(Boolean));
    const gone = [...new Set(dropped.map((d) => d.receipt?.receipt_path).filter((p): p is string => !!p && !keep.has(p)))];
    await Promise.all(gone.map((path) =>
      api.delete(`/api/jobs/${jobId}/receipts?${new URLSearchParams({ path })}`).catch(() => undefined)));
  }

  async function addAll() {
    const chosen = drafts.filter((d) => d.include);
    const bad = chosen.find((d) => { const c = parseCents(d.amount); return c === null || c === undefined || c <= 0; });
    if (bad) { toast(`Check the amount on ${bad.payee || bad.fileName}.`); return; }
    setAdding(true);
    let added = 0;
    try {
      for (const d of chosen) {
        await api.post(`/api/jobs/${jobId}/expenses`, {
          spent_on: d.spent_on || null, payee: d.payee, description: d.description,
          amount_cents: parseCents(d.amount), category: d.category, ...(d.receipt ?? {}),
        });
        added++;
      }
      await discardFiles(chosen, drafts.filter((d) => !d.include));
      setDrafts([]);
      setProblems([]);
      toast(`${added} ${added === 1 ? "line" : "lines"} added to the PC log.`);
    } catch (err) {
      // Whatever went in, stays in; the rest stay here to try again.
      setDrafts((all) => all.filter((d) => !chosen.slice(0, added).includes(d)));
      toast(err instanceof Error ? `Couldn't add them all: ${err.message}` : "Couldn't add them all.");
    } finally {
      setAdding(false);
      await onAdded();
    }
  }

  async function discardAll() {
    await discardFiles([], drafts);
    setDrafts([]);
    setProblems([]);
  }

  const count = drafts.filter((d) => d.include).length;

  return (
    <section className="card p-4 mb-5 grid gap-3" aria-label="Read receipts"
      onDragEnter={(e) => { if (!isFileDrag(e)) return; depth.current += 1; setDragging(true); }}
      onDragOver={(e) => { if (!isFileDrag(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = reading ? "none" : "copy"; }}
      onDragLeave={(e) => { if (!isFileDrag(e)) return; depth.current = Math.max(0, depth.current - 1); if (!depth.current) setDragging(false); }}
      onDrop={(e) => {
        if (!isFileDrag(e)) return;
        e.preventDefault();
        depth.current = 0;
        setDragging(false);
        if (!reading) read(Array.from(e.dataTransfer.files));
      }}>
      <div>
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Read receipts</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Photos or PDFs. Claude drafts a line from each; nothing goes on the log until you add it, and the receipt is kept with its line.
        </p>
      </div>
      <div className="rounded-lg p-5 grid gap-3 justify-items-center text-center"
        style={{
          border: `2px dashed ${dragging ? "var(--accent)" : "var(--border-strong)"}`,
          background: dragging ? "var(--accent-subtle)" : "var(--bg-inset)",
          transition: "background 120ms, border-color 120ms",
        }}>
        <p className="text-sm" style={{ color: "var(--text-primary)" }} aria-live="polite">
          {reading ? `Reading ${Math.min(reading.done + 1, reading.total)} of ${reading.total}…`
            : dragging ? "Drop to read them" : (
              <>
                Drop receipts here, or{" "}
                <label className="underline" style={{ color: "var(--accent-text)", cursor: "pointer" }}>
                  choose them
                  <input key={inputKey} type="file" multiple accept={ACCEPT} className="sr-only" disabled={!!reading}
                    onChange={(e) => read(Array.from(e.target.files ?? []))} />
                </label>
              </>
            )}
        </p>
        <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
          These are all
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="field-ghost" style={{ width: "auto" }}
            disabled={!!reading}>
            <option value="">Let Claude pick the column</option>
            {cats.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </label>
      </div>

      {problems.length > 0 && (
        <ul className="text-xs grid gap-0.5" style={{ color: "var(--warning)" }} role="status">
          {problems.map((p, i) => <li key={i}><span style={{ color: "var(--text-secondary)" }}>{p.fileName}:</span> {p.message}</li>)}
        </ul>
      )}

      {drafts.length > 0 && (
        <>
          <div className="data-table-raised">
            <table>
              <thead>
                <tr>
                  <th aria-label="Add" />
                  <th>Date</th><th>To whom paid</th><th style={{ minWidth: "12rem" }}>For what</th>
                  <th style={{ textAlign: "right" }}>Amount</th><th>Column</th><th>From</th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((d) => (
                  <tr key={d.key} style={{ opacity: d.include ? 1 : 0.5 }}>
                    <td><input type="checkbox" checked={d.include} onChange={(e) => set(d.key, { include: e.target.checked })}
                      aria-label={`Add ${d.payee || d.fileName}`} /></td>
                    <td><DateInput value={d.spent_on} onChange={(v) => set(d.key, { spent_on: v })} ariaLabel="Receipt date" className="field-ghost" /></td>
                    <td><input value={d.payee} onChange={(e) => set(d.key, { payee: e.target.value })} maxLength={200}
                      aria-label="To whom paid" className="field-ghost" /></td>
                    <td><input value={d.description} onChange={(e) => set(d.key, { description: e.target.value })} maxLength={500}
                      aria-label="For what" className="field-ghost" /></td>
                    <td style={{ textAlign: "right" }}><input value={d.amount} onChange={(e) => set(d.key, { amount: e.target.value })}
                      inputMode="decimal" aria-label="Amount" className="field-ghost date-text" style={{ width: "10ch", textAlign: "right" }} /></td>
                    <td><select value={d.category} onChange={(e) => set(d.key, { category: e.target.value })} className="field-ghost"
                      style={{ width: "auto" }} aria-label="Column">
                      {cats.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select></td>
                    <td className="text-xs" style={{ color: "var(--text-muted)", maxWidth: "10rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      title={d.fileName}>{d.fileName}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" className="btn btn-primary btn-sm" disabled={adding || !!reading || !count} onClick={addAll}>
              {adding ? "Adding…" : `Add ${count} ${count === 1 ? "line" : "lines"} to the log`}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={adding || !!reading} onClick={discardAll}>Discard</button>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>Check each one against its receipt before adding.</span>
          </div>
        </>
      )}
    </section>
  );
}
