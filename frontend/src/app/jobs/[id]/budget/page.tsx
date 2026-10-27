"use client";

/* Job home, Budget tab — the Estimate view (docs/estimate-reconcile-plan.md,
 * PR 1). The estimate as quoted, line by line, under its own headings, each
 * line carrying its billing basis: Fee bills as quoted, Fixed bills the quoted
 * amount whatever it costs, At cost bills what it costs plus any markup. The
 * basis is recorded here, once, and Reconcile (PR 3) reads it.
 *
 * qty × rate is worked out by the API, and so is every subtotal and total
 * (services/budget.py). Nothing is added up in this file.
 *
 * Most estimates already exist as a PDF or a spreadsheet: "Read an estimate"
 * (ImportEstimate.tsx) drafts the lines and a basis for each. Adding by hand
 * is the same table.
 *
 * Reconcile (Reconcile.tsx) is the same lines with what each cost and billed.
 *
 * Marking the estimate signed locks its quantities, rates and amounts; the
 * API refuses a change to them (409) rather than this page merely hiding it.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { useToast } from "@/components/Toast";
import { bpToPct, centsToInput, formatCents, parseBp, parseCents } from "@/lib/money";
import { ImportEstimate } from "./ImportEstimate";
import { Reconcile, type RLine, type RTotals, type Statement } from "./Reconcile";

type Bucket = "fee" | "rate" | "pass";
type FloorKind = "production_fee" | "insurance" | "contingency";
interface Line {
  id: string; bucket: Bucket; block: string | null; section?: string | null; name: string;
  qty: number | string | null; unit_amount_cents: number | null; est_cents: number | null;
  markup_bp: number; floor_kind: FloorKind | null;
}
interface Section { name: string | null; est_cents: number; lines: number }
interface Floor { kind: FloorKind; line_id: string | null; quoted: boolean }
interface Budget {
  migrated: boolean;
  lines: (Line & RLine)[];
  blocks: string[];
  statement: Statement;
  unassigned_receipts: { count: number; cents: number };
  estimate: { ready: boolean; signed_on: string | null; sections: Section[] };
  budget: Omit<RTotals, "floor_lines"> & { floor_lines: Floor[] };
}

const BASIS: { key: Bucket; label: string; hint: string }[] = [
  { key: "fee", label: "Fee", hint: "Bills as quoted" },
  { key: "rate", label: "Fixed", hint: "Bills the quoted amount, whatever it costs" },
  { key: "pass", label: "At cost", hint: "Bills what it costs, plus any markup" },
];
const FLOOR_LABEL: Record<FloorKind, string> = {
  production_fee: "Production fee", insurance: "Insurance", contingency: "Contingency",
};

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${m}/${d}/${String(y % 100).padStart(2, "0")}`;
}

function qtyText(q: number | string | null): string {
  return q === null || q === "" ? "" : String(Number(q));
}

/** "3", "2.5" → a number; blank → null; anything else → undefined. */
function parseQty(text: string): number | null | undefined {
  const t = text.trim();
  if (t === "") return null;
  return /^\d{1,6}(\.\d{1,2})?$/.test(t) ? Number(t) : undefined;
}

/** A figure that isn't editable, padded like the .field-ghost inputs beside
 * it so a row's numbers sit on one line. */
function Figure({ children, title }: { children: React.ReactNode; title?: string }) {
  return <span title={title} style={{ display: "inline-block", padding: "0.375rem 0.5rem" }}><DateText>{children}</DateText></span>;
}

function sectionOf(line: Line): string | null {
  return (line.section ?? "").trim() || null;
}

export default function BudgetPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Budget | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [view, setView] = useState<"estimate" | "reconcile" | null>(null);
  // Reconcile's market chips: "*" everything, "project" the whole-job lines, or a market.
  const [block, setBlock] = useState("*");
  const { show: showToast, node: toastNode } = useToast();

  const fetchBudget = useCallback(
    (b: string) => api.get<Budget>(`/api/jobs/${id}/budget${b === "*" ? "" : `?${new URLSearchParams({ block: b })}`}`),
    [id]);
  const load = useCallback(() => {
    setLoadError(false);
    return fetchBudget(block).then(setData).catch(() => setLoadError(true));
  }, [fetchBudget, block]);
  useEffect(() => { load(); }, [load]);

  /** One write; every route answers with the budget as the API now works it
   * out — for the whole job, so a market filter fetches its own totals after. */
  async function run(tag: string, write: () => Promise<unknown>, done?: string): Promise<boolean> {
    setBusy(tag);
    try {
      const out = (await write()) as Budget;
      setData(block === "*" ? out : await fetchBudget(block));
      if (done) showToast(done);
      return true;
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that change.");
      load();
      return false;
    } finally {
      setBusy(null);
    }
  }

  const update = (line: { id: string }, body: Record<string, unknown>) =>
    run(line.id, () => api.put(`/api/jobs/${id}/budget/lines/${line.id}`, body));
  const add = (body: Record<string, unknown>, done = "Line added.") =>
    run("add", () => api.post(`/api/jobs/${id}/budget/lines`, body), done);

  if (loadError) return <LoadError message="Couldn't load the budget." onRetry={load} />;
  if (!data) return <TableSkeleton />;

  const { estimate: est, budget: t } = data;
  const signed = !!est.signed_on;
  // A signed estimate opens on Reconcile; a draft on the estimate itself.
  const shown = view ?? (signed ? "reconcile" : "estimate");
  const missingFloors = t.floor_lines.filter((f) => !f.line_id);
  const names = est.sections.map((s) => s.name).filter((n): n is string => !!n);
  const showHeadings = est.sections.some((s) => s.name);

  return (
    <div>
      {toastNode}

      <div className="mb-3">
        <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Budget</h2>
        <p className="text-xs max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          The estimate as quoted, line by line. Each line&apos;s basis decides how it reconciles:{" "}
          {BASIS.map((b, i) => (
            <span key={b.key}>{i > 0 && "; "}<strong style={{ fontWeight: 600 }}>{b.label}</strong> {b.hint.toLowerCase()}</span>
          ))}.
        </p>
      </div>

      {!data.migrated && (
        <div className="next-step mb-5" role="status">
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span className="next-step-label">Not set up</span>
            This server doesn&apos;t have the budget tables yet, so lines can&apos;t be saved.
          </p>
        </div>
      )}
      {data.migrated && !est.ready && (
        <div className="next-step mb-5" role="status">
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span className="next-step-label">Not set up</span>
            Headings and signing the estimate aren&apos;t on this server yet. Lines still save.
          </p>
        </div>
      )}

      {est.ready && (
        <SignCard signedOn={est.signed_on} hasQuote={t.estimate_cents > 0 || data.lines.some((l) => l.est_cents !== null)}
          busy={busy === "sign"}
          onSign={(date) => run("sign", () => api.put(`/api/jobs/${id}/estimate`, { signed_on: date }),
            "Marked signed. Quantities, rates and amounts are locked.")}
          onUnlock={() => run("sign", () => api.put(`/api/jobs/${id}/estimate`, { signed_on: null }), "Unlocked.")} />
      )}

      <div className="flex gap-1 mb-4" role="tablist" aria-label="Budget view">
        {(["estimate", "reconcile"] as const).map((v) => (
          <button key={v} type="button" role="tab" aria-selected={shown === v} className={`nav-item${shown === v ? " active" : ""}`}
            onClick={() => { setView(v); if (v === "estimate") setBlock("*"); }}>
            {v === "estimate" ? "Estimate" : "Reconcile"}
          </button>
        ))}
      </div>

      {shown === "reconcile" ? (
        <Reconcile jobId={id} lines={data.lines} totals={t} blocks={data.blocks} block={block} setBlock={setBlock}
          busy={busy} toast={showToast} onUpdate={update} onAdd={(body) => add(body, "Cost added.")}
          statement={data.statement} unassigned={data.unassigned_receipts}
          onSaveStatement={(body) => run("statement", () => api.put(`/api/jobs/${id}/budget/statement`, body), "Saved.")} />
      ) : (<>
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 mb-4 text-sm" aria-label="Estimate totals">
        <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
          Estimate <DateText>{formatCents(t.estimate_cents)}</DateText>
        </span>
        {BASIS.map((b) => (
          <span key={b.key} style={{ color: "var(--text-secondary)" }}>
            {b.label} <DateText>{formatCents(t.by_bucket[b.key]?.est_cents ?? 0)}</DateText>
          </span>
        ))}
      </div>

      {!signed && data.migrated && (
        <ImportEstimate<Budget> jobId={id} toast={showToast} onAdded={setData} />
      )}

      {!signed && data.migrated && data.lines.length > 0 && missingFloors.length > 0 && (
        <div className="card p-4 mb-4 flex flex-wrap items-center gap-3 text-sm">
          <span style={{ color: "var(--text-secondary)" }}>
            Not on this estimate: {missingFloors.map((f) => FLOOR_LABEL[f.kind]).join(", ")}. Add each one, at $0 if
            it&apos;s left off on purpose.
          </span>
          <span className="flex flex-wrap gap-2">
            {missingFloors.map((f) => (
              <button key={f.kind} type="button" className="btn btn-secondary btn-sm" disabled={!!busy}
                onClick={() => add({ name: FLOOR_LABEL[f.kind], bucket: "fee", floor_kind: f.kind }, `${FLOOR_LABEL[f.kind]} added.`)}>
                + {FLOOR_LABEL[f.kind]}
              </button>
            ))}
          </span>
        </div>
      )}

      <div className="data-table-raised mb-4">
        <table>
          <thead>
            <tr>
              <th style={{ minWidth: "14rem" }}>Description</th>
              <th>Market</th>
              <th style={{ textAlign: "right" }}>Qty</th>
              <th style={{ textAlign: "right" }}>Rate</th>
              <th style={{ textAlign: "right" }}>Amount</th>
              <th>Basis</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {data.lines.length === 0 && (
              <tr><td colSpan={7} className="text-sm" style={{ color: "var(--text-muted)" }}>
                Nothing on the estimate yet. Add its lines below, under the same headings it uses.
              </td></tr>
            )}
            {est.sections.map((s) => (
              <SectionRows key={s.name ?? ""} section={s} showHeading={showHeadings} ready={est.ready} busy={busy}
                lines={data.lines.filter((l) => sectionOf(l) === s.name)} locked={signed} toast={showToast}
                onRename={(to) => run(`section:${s.name}`, () => api.put(`/api/jobs/${id}/budget/sections`, { name: s.name, to }))}
                onUpdate={update}
                onRemove={(line) => run(line.id, () => api.delete(`/api/jobs/${id}/budget/lines/${line.id}`), "Line removed.")} />
            ))}
            {data.lines.length > 0 && (
              <tr>
                <td colSpan={4} className="text-sm font-semibold" style={{ color: "var(--text-primary)", verticalAlign: "middle" }}>Estimate total</td>
                <td style={{ textAlign: "right" }}>
                  <Figure><span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{formatCents(t.estimate_cents)}</span></Figure>
                </td>
                <td colSpan={2} />
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {data.migrated && !signed && (
        <AddLine sections={names} ready={est.ready} busy={busy === "add"} toast={showToast} onAdd={add} />
      )}
      </>)}
    </div>
  );
}

function SignCard({ signedOn, hasQuote, busy, onSign, onUnlock }: {
  signedOn: string | null; hasQuote: boolean; busy: boolean;
  onSign: (date: string) => Promise<boolean>; onUnlock: () => Promise<boolean>;
}) {
  const [date, setDate] = useState(today());
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="card p-4 mb-4 flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm" style={{ color: "var(--text-primary)" }}>
        {signedOn ? (
          <>Signed <DateText>{shortDate(signedOn)}</DateText>.{" "}
            <span style={{ color: "var(--text-secondary)" }}>Quantities, rates and amounts are locked; headings, basis and market still edit.</span></>
        ) : (
          <>Draft. <span style={{ color: "var(--text-secondary)" }}>Mark it signed once the client has agreed it, and the quoted figures lock.</span></>
        )}
      </p>
      {signedOn ? (
        confirm ? (
          <span className="flex items-center gap-2">
            <button type="button" className="btn btn-sm btn-confirm-remove" disabled={busy}
              onClick={async () => { if (await onUnlock()) setConfirm(false); }}>
              {busy ? "Unlocking…" : "Unlock: amounts can change again"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(false)}>Cancel</button>
          </span>
        ) : (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(true)}>Unlock</button>
        )
      ) : (
        <span className="flex items-center gap-2">
          <DateInput value={date} ariaLabel="Date the estimate was signed" className="field-ghost" onChange={setDate} />
          <button type="button" className="btn btn-primary btn-sm" disabled={busy || !hasQuote || !date}
            onClick={() => onSign(date)}>
            {busy ? "Saving…" : "Mark signed"}
          </button>
        </span>
      )}
    </div>
  );
}

function SectionRows({ section, showHeading, ready, lines, locked, busy, toast, onRename, onUpdate, onRemove }: {
  section: Section; showHeading: boolean; ready: boolean; lines: Line[]; locked: boolean; busy: string | null;
  toast: (m: string) => void; onRename: (to: string | null) => void;
  onUpdate: (line: Line, body: Record<string, unknown>) => void; onRemove: (line: Line) => Promise<boolean>;
}) {
  return (
    <>
      {showHeading && (
        <tr>
          <td colSpan={4} style={{ background: "var(--bg-inset)" }}>
            <input key={`s-${section.name}`} defaultValue={section.name ?? ""} placeholder="No heading" maxLength={120}
              disabled={!ready || busy === `section:${section.name}`} aria-label={`Heading ${section.name ?? "(none)"}`}
              className="field-ghost text-sm font-semibold" style={{ color: "var(--text-primary)" }}
              onBlur={(e) => { const to = e.target.value.trim() || null; if (to !== section.name) onRename(to); }}
              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
          </td>
          <td style={{ textAlign: "right", background: "var(--bg-inset)" }}>
            <Figure><span style={{ color: "var(--text-secondary)" }}>{formatCents(section.est_cents)}</span></Figure>
          </td>
          <td colSpan={2} style={{ background: "var(--bg-inset)" }} />
        </tr>
      )}
      {lines.map((l) => (
        <LineRow key={l.id} line={l} locked={locked} busy={busy === l.id} toast={toast}
          onUpdate={(body) => onUpdate(l, body)} onRemove={() => onRemove(l)} />
      ))}
    </>
  );
}

function LineRow({ line, locked, busy, toast, onUpdate, onRemove }: {
  line: Line; locked: boolean; busy: boolean; toast: (m: string) => void;
  onUpdate: (body: Record<string, unknown>) => void; onRemove: () => Promise<boolean>;
}) {
  const [confirm, setConfirm] = useState(false);
  const derived = line.qty !== null && line.qty !== "" && line.unit_amount_cents !== null;
  const blurOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === "Enter") e.currentTarget.blur(); };

  function money(field: "unit_amount_cents" | "est_cents", text: string) {
    const cents = parseCents(text);
    if (cents === undefined) { toast("That isn't an amount."); return; }
    if (cents !== line[field]) onUpdate({ [field]: cents });
  }

  return (
    <tr>
      <td>
        <span className="grid gap-0.5">
          <input key={`n-${line.id}-${line.name}`} defaultValue={line.name} maxLength={200} aria-label="Description"
            className="field-ghost" disabled={busy}
            onBlur={(e) => {
              const v = e.target.value.trim();
              if (!v) { e.target.value = line.name; return; }
              if (v !== line.name) onUpdate({ name: v });
            }}
            onKeyDown={blurOnEnter} />
          {line.floor_kind && (
            <span className="flex items-center gap-1.5">
              <span className="custom-pill">Floor line</span>
              {line.est_cents === null && (
                <span className="text-xs" style={{ color: "var(--warning)" }}>No amount yet: $0 if it&apos;s left off on purpose</span>
              )}
            </span>
          )}
        </span>
      </td>
      <td>
        <input key={`b-${line.id}-${line.block}`} defaultValue={line.block ?? ""} placeholder="Whole job" maxLength={80}
          aria-label={`Market for ${line.name}`} className="field-ghost" style={{ width: "9ch" }} disabled={busy}
          onBlur={(e) => { const v = e.target.value.trim() || null; if (v !== line.block) onUpdate({ block: v }); }}
          onKeyDown={blurOnEnter} />
      </td>
      <td style={{ textAlign: "right" }}>
        {locked ? <Figure>{qtyText(line.qty)}</Figure> : (
          <input key={`q-${line.id}-${line.qty}`} defaultValue={qtyText(line.qty)} inputMode="decimal" aria-label={`Quantity for ${line.name}`}
            className="field-ghost date-text" style={{ width: "6ch", textAlign: "right" }} disabled={busy}
            onBlur={(e) => {
              const q = parseQty(e.target.value);
              if (q === undefined) { toast("A quantity is a number, like 3 or 2.5."); e.target.value = qtyText(line.qty); return; }
              if (q !== (line.qty === null || line.qty === "" ? null : Number(line.qty))) onUpdate({ qty: q });
            }}
            onKeyDown={blurOnEnter} />
        )}
      </td>
      <td style={{ textAlign: "right" }}>
        {locked ? <Figure>{formatCents(line.unit_amount_cents)}</Figure> : (
          <input key={`r-${line.id}-${line.unit_amount_cents}`} defaultValue={centsToInput(line.unit_amount_cents)} inputMode="decimal"
            aria-label={`Rate for ${line.name}`} className="field-ghost date-text" style={{ width: "10ch", textAlign: "right" }}
            disabled={busy} onBlur={(e) => money("unit_amount_cents", e.target.value)} onKeyDown={blurOnEnter} />
        )}
      </td>
      <td style={{ textAlign: "right" }}>
        {locked || derived ? (
          <Figure title={derived ? "Quantity × rate" : undefined}>{formatCents(line.est_cents) || "—"}</Figure>
        ) : (
          <input key={`a-${line.id}-${line.est_cents}`} defaultValue={centsToInput(line.est_cents)} inputMode="decimal"
            aria-label={`Amount for ${line.name}`} className="field-ghost date-text" style={{ width: "11ch", textAlign: "right" }}
            disabled={busy} onBlur={(e) => money("est_cents", e.target.value)} onKeyDown={blurOnEnter} />
        )}
      </td>
      <td>
        <span className="flex items-center gap-1.5" style={{ whiteSpace: "nowrap" }}>
          <select value={line.bucket} disabled={busy} className="field-ghost" style={{ width: "auto" }}
            aria-label={`Basis for ${line.name}`} title={BASIS.find((b) => b.key === line.bucket)?.hint}
            onChange={(e) => onUpdate({ bucket: e.target.value })}>
            {BASIS.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
          </select>
          {line.bucket === "pass" && (
            <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
              +
              <input key={`m-${line.id}-${line.markup_bp}`} defaultValue={line.markup_bp ? bpToPct(line.markup_bp) : ""} placeholder="0" inputMode="decimal"
                onFocus={(e) => e.currentTarget.select()}
                aria-label={`Markup percent for ${line.name}`} className="field-ghost date-text"
                style={{ width: "5ch", textAlign: "right" }} disabled={busy}
                onBlur={(e) => {
                  const bp = parseBp(e.target.value || "0");
                  if (bp === undefined) { toast("A markup is a percent, like 15."); e.target.value = bpToPct(line.markup_bp); return; }
                  if (bp !== line.markup_bp) onUpdate({ markup_bp: bp });
                }}
                onKeyDown={blurOnEnter} />%
            </label>
          )}
        </span>
      </td>
      <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
        {locked && line.est_cents !== null ? null : confirm ? (
          <>
            <button type="button" className="btn btn-sm btn-confirm-remove" disabled={busy}
              onClick={async () => { if (await onRemove()) setConfirm(false); }}>Remove this line</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(false)}>Cancel</button>
          </>
        ) : (
          <button type="button" className="btn btn-remove" onClick={() => setConfirm(true)} aria-label={`Remove ${line.name}`}>Remove</button>
        )}
      </td>
    </tr>
  );
}

function AddLine({ sections, ready, busy, toast, onAdd }: {
  sections: string[]; ready: boolean; busy: boolean; toast: (m: string) => void;
  onAdd: (body: Record<string, unknown>) => Promise<boolean>;
}) {
  const [section, setSection] = useState("");
  const [name, setName] = useState("");
  const [qty, setQty] = useState("");
  const [rate, setRate] = useState("");
  const [amount, setAmount] = useState("");
  const [bucket, setBucket] = useState<Bucket>("rate");
  const both = qty.trim() !== "" && rate.trim() !== "";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = parseQty(qty), r = parseCents(rate), a = both ? null : parseCents(amount);
    if (!name.trim()) { toast("Give the line a description."); return; }
    if (q === undefined) { toast("A quantity is a number, like 3 or 2.5."); return; }
    if (r === undefined || a === undefined) { toast("That isn't an amount."); return; }
    const ok = await onAdd({
      name, bucket, qty: q, unit_amount_cents: r, est_cents: a,
      ...(ready && section.trim() ? { section: section.trim() } : {}),
    });
    // The heading stays, so a section's lines go in one after another.
    if (ok) { setName(""); setQty(""); setRate(""); setAmount(""); }
  }

  return (
    <form className="card p-4 grid gap-3" onSubmit={submit} aria-label="Add a line">
      <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Add a line</h3>
      <div className={`grid gap-3 items-end ${ready ? "md:grid-cols-[1fr_1.5fr_auto_auto_auto_auto_auto]" : "md:grid-cols-[1.5fr_auto_auto_auto_auto_auto]"}`}>
        {ready && (
          <div>
            <label htmlFor="b-section" className="field-label">Heading</label>
            <input id="b-section" value={section} onChange={(e) => setSection(e.target.value)} list="b-sections"
              maxLength={120} placeholder="Crew expenses" className="field-input" />
            <datalist id="b-sections">{sections.map((s) => <option key={s} value={s} />)}</datalist>
          </div>
        )}
        <div>
          <label htmlFor="b-name" className="field-label">Description</label>
          <input id="b-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} className="field-input" required />
        </div>
        <div>
          <label htmlFor="b-qty" className="field-label">Qty</label>
          <input id="b-qty" value={qty} onChange={(e) => setQty(e.target.value)} inputMode="decimal" placeholder="3"
            className="field-input date-text" style={{ width: "6ch" }} />
        </div>
        <div>
          <label htmlFor="b-rate" className="field-label">Rate</label>
          <input id="b-rate" value={rate} onChange={(e) => setRate(e.target.value)} inputMode="decimal" placeholder="0.00"
            className="field-input date-text" style={{ width: "10ch" }} />
        </div>
        <div>
          <label htmlFor="b-amount" className="field-label">Amount</label>
          <input id="b-amount" value={both ? "" : amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal"
            placeholder={both ? "qty × rate" : "0.00"} disabled={both} className="field-input date-text" style={{ width: "11ch" }} />
        </div>
        <div>
          <label htmlFor="b-basis" className="field-label">Basis</label>
          <select id="b-basis" value={bucket} onChange={(e) => setBucket(e.target.value as Bucket)} className="field-input">
            {BASIS.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
          </select>
        </div>
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
      </div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        With a quantity and a rate, the amount is worked out. Fixed is right for crew days and gear quoted as a set
        amount; At cost for flights, lodging and anything the estimate marks &ldquo;estimated&rdquo;.
      </p>
    </form>
  );
}
