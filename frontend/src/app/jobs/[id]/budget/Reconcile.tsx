"use client";

/* Budget → Reconcile (docs/estimate-reconcile-plan.md, PR 3; the model is
 * docs/setready-budget-reconciliation-handoff.md). The same lines as the
 * Estimate view, now with what each one cost and billed.
 *
 * Profit/Loss means something different per basis, and that's the whole
 * reason the bases exist: a Fee line's billing IS profit; a Fixed line keeps
 * whatever it didn't cost; an At cost line bills its cost (plus any markup),
 * so only its variance from the estimate matters. A netted budget-vs-actual
 * table would read intended margin as an underrun — so there isn't one.
 *
 * Every figure comes from the API (services/budget.py), filtered by market
 * there too. Nothing is added up in this file. Receipts on the PC log can be
 * pointed at a line; then that line's actual IS their sum, and isn't typed.
 *
 * The client statement (StatementCard) is the one thing here that leaves the
 * building: two columns, Estimated and This project, with each line's note as
 * its reason. Built live by the API (services/reconciliation_statement.py) —
 * nothing about cost or profit reaches it.
 */

import { useRef, useState } from "react";
import Link from "next/link";
import { downloadFile } from "@/lib/api";
import { triggerDownload } from "@/lib/download";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { bpToPct, centsToInput, formatCents, parseCents } from "@/lib/money";

type Bucket = "fee" | "rate" | "pass";
export interface RLine {
  id: string; bucket: Bucket; block: string | null; section?: string | null; name: string;
  est_cents: number | null; act_cents: number | null; bill_cents: number | null; markup_bp: number;
  dropped: boolean; awaiting_cost: boolean; act_paid: boolean; floor_kind: string | null; note: string | null;
  act_from_expenses: boolean; expense_count: number; act_open: boolean;
  calc: {
    billed_cents: number | null; cost_cents: number | null; profit_loss_cents: number | null;
    unreconciled_cents: number; diff_cents: number | null; unquoted: boolean; derived: boolean;
  };
}
interface Named { id: string; name: string; block: string | null; cents: number; why?: string }
interface BucketTotals { billed_cents: number; cost_cents: number; profit_loss_cents: number; est_cents: number; act_cents: number; diff_cents: number }
export interface RTotals {
  billed_cents: number; cost_cents: number; profit_loss_cents: number; unreconciled_cents: number;
  margin_bp: number | null; estimate_cents: number; projected_billing_cents: number;
  by_bucket: Record<Bucket, BucketTotals>;
  unreconciled: Named[]; unquoted: Named[]; unquoted_cents: number;
  dropped: Named[]; dropped_scope_cents: number; expense_variance_cents: number;
  over_variance_band: { id: string; name: string; over_bp: number }[];
  markup_to_bill_cents: number;
  floor_lines: { kind: string; line_id: string | null; quoted: boolean }[];
  invoiced_cents: number; received_cents: number; left_to_invoice_cents: number;
  cash_in_hand_cents: number; committed_cents: number; after_committed_cents: number;
}

const BASIS: { key: Bucket; label: string }[] = [{ key: "fee", label: "Fee" }, { key: "rate", label: "Fixed" }, { key: "pass", label: "At cost" }];
const FLOOR_LABEL: Record<string, string> = { production_fee: "Production fee", insurance: "Insurance", contingency: "Contingency" };

/** A figure that isn't editable, padded like the inputs beside it. */
function Figure({ children, tone }: { children: React.ReactNode; tone?: "muted" | "good" | "bad" | "strong" }) {
  const color = tone === "muted" ? "var(--text-muted)" : tone === "good" ? "var(--success)" : tone === "bad" ? "var(--danger)" : "var(--text-primary)";
  return (
    <span style={{ display: "inline-block", padding: "0.375rem 0.5rem", color, fontWeight: tone === "strong" ? 600 : undefined }}>
      <DateText>{children}</DateText>
    </span>
  );
}

function signed(cents: number): "good" | "bad" | undefined {
  return cents > 0 ? "good" : cents < 0 ? "bad" : undefined;
}

function sectionOf(line: RLine): string | null {
  return (line.section ?? "").trim() || null;
}

export interface Statement { ready: boolean; client_contact: string; estimate_ref: string; intro: string }

export function Reconcile({ jobId, lines, totals, blocks, block, setBlock, busy, toast, onUpdate, onAdd, statement, onSaveStatement, unassigned }: {
  jobId: string; lines: RLine[]; totals: RTotals; blocks: string[]; block: string; setBlock: (b: string) => void;
  unassigned: { count: number; cents: number };
  busy: string | null; toast: (m: string) => void;
  onUpdate: (line: RLine, body: Record<string, unknown>) => void;
  onAdd: (body: Record<string, unknown>) => Promise<boolean>;
  statement: Statement; onSaveStatement: (body: Record<string, string>) => Promise<boolean>;
}) {
  const t = totals;
  const shown = lines.filter((l) => block === "*" || (block === "project" ? !l.block : l.block === block));
  const sections: (string | null)[] = [];
  for (const l of shown) if (!sections.includes(sectionOf(l))) sections.push(sectionOf(l));
  const missingFloors = t.floor_lines.filter((f) => !f.quoted);

  return (
    <div className="grid gap-4">
      {blocks.length > 0 && (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show a market">
          {[["*", "All"], ["project", "Whole job"], ...blocks.map((b) => [b, b])].map(([key, label]) => (
            <button key={key} type="button" className={`nav-item${block === key ? " active" : ""}`} onClick={() => setBlock(key)}
              aria-pressed={block === key}>{label}</button>
          ))}
        </div>
      )}

      <Summary t={t} />

      {unassigned.count > 0 && (
        <p className="text-xs -mt-2" style={{ color: "var(--text-secondary)" }} role="status">
          {unassigned.count} PC log {unassigned.count === 1 ? "receipt" : "receipts"} (<DateText>{formatCents(unassigned.cents)}</DateText>)
          {unassigned.count === 1
            ? " isn't against an estimate line, so it's in no line's cost yet. Pick a line for it on the "
            : " aren't against an estimate line, so they're in no line's cost yet. Pick a line for each on the "}
          <Link href={`/jobs/${jobId}/pc-log`} style={{ color: "var(--accent-text)" }}>PC log</Link>.
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <BucketCard title="Fee lines" note="Billed as quoted. With no cost under them, the billing is profit." rows={[
          ["Billed", t.by_bucket.fee.billed_cents],
        ]} />
        <BucketCard title="Fixed" note="Billed at the quoted amount whatever it cost. What it didn't cost is kept." rows={[
          ["Billed", t.by_bucket.rate.billed_cents], ["Cost", t.by_bucket.rate.cost_cents],
          ["Kept", t.by_bucket.rate.profit_loss_cents, true],
        ]} />
        <BucketCard title="At cost" note="Billed at what it cost, plus any markup. Only the variance from the estimate matters." rows={[
          ["Estimated", t.by_bucket.pass.est_cents], ["Cost", t.by_bucket.pass.cost_cents],
          [t.by_bucket.pass.diff_cents >= 0 ? "Under estimate" : "Over estimate", Math.abs(t.by_bucket.pass.diff_cents)],
          ...(t.markup_to_bill_cents ? [["Markup billed", t.markup_to_bill_cents, true] as [string, number, boolean]] : []),
        ]} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {t.unreconciled.length > 0 && (
          <Panel title="Billing with no cost logged yet" total={t.unreconciled_cents} items={t.unreconciled}
            note="Quoted and billable, no invoice in. Read profit as a ceiling until these land." />
        )}
        {t.unquoted.length > 0 && (
          <Panel title="Costs that weren't on the estimate" total={t.unquoted_cents} items={t.unquoted} tone="bad"
            note="A Fixed line with no quote bills nothing, so its whole cost comes off the margin." />
        )}
        {t.dropped.length > 0 && (
          <Panel title="Dropped scope" total={t.dropped_scope_cents} items={t.dropped}
            note={`Not shot, days not worked, fees cut. ${t.expense_variance_cents
              ? `With At cost lines billing ${formatCents(Math.abs(t.expense_variance_cents))} ${t.expense_variance_cents > 0 ? "less" : "more"} than estimated (markup included), that's`
              : "That's"} the whole move from the estimate, ${formatCents(t.estimate_cents)}, to projected billing, ${formatCents(t.projected_billing_cents)}.`} />
        )}
        {missingFloors.length > 0 && (
          <section className="card p-4 text-sm" aria-label="Floor lines">
            <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Not on the estimate</h3>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {missingFloors.map((f) => FLOOR_LABEL[f.kind] ?? f.kind).join(", ")}. Present on every estimate, at $0 if left off on purpose,
              so the job is seen to cover them or not.
            </p>
          </section>
        )}
        {t.over_variance_band.length > 0 && (
          <section className="card p-4 text-sm" aria-label="Over the variance band">
            <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>More than 10% over</h3>
            <ul className="grid gap-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
              {t.over_variance_band.map((o) => <li key={o.id}>{o.name} <DateText>+{bpToPct(o.over_bp)}%</DateText></li>)}
            </ul>
          </section>
        )}
      </div>

      <div className="data-table-raised">
        <table>
          <thead>
            <tr>
              <th style={{ minWidth: "13rem" }}>Line</th>
              <th>Basis</th>
              <th style={{ textAlign: "right" }}>Estimated</th>
              <th style={{ textAlign: "right" }} title="Fixed lines only: what it bills at when the scope moved">Billing at</th>
              <th style={{ textAlign: "right" }}>Actual</th>
              <th style={{ textAlign: "right" }}>Difference</th>
              <th style={{ textAlign: "right" }}>Profit/Loss</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={7} className="text-sm" style={{ color: "var(--text-muted)" }}>
                {lines.length ? "No lines in this market." : "Nothing on the estimate yet. Build it on the Estimate view first."}
              </td></tr>
            )}
            {sections.map((s) => (
              <SectionBlock key={s ?? ""} name={s} showHeading={sections.some(Boolean)}
                lines={shown.filter((l) => sectionOf(l) === s)} busy={busy} toast={toast} onUpdate={onUpdate} />
            ))}
          </tbody>
        </table>
      </div>

      <AddCost blocks={blocks} busy={busy === "add"} toast={toast} onAdd={onAdd} />

      <Cash t={t} jobId={jobId} />

      <StatementCard jobId={jobId} statement={statement} hasEstimate={t.estimate_cents > 0} busy={busy === "statement"}
        toast={toast} onSave={onSaveStatement} />
    </div>
  );
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function StatementCard({ jobId, statement, hasEstimate, busy, toast, onSave }: {
  jobId: string; statement: Statement; hasEstimate: boolean; busy: boolean; toast: (m: string) => void;
  onSave: (body: Record<string, string>) => Promise<boolean>;
}) {
  const [on, setOn] = useState(today());
  const [downloading, setDownloading] = useState(false);

  async function download() {
    setDownloading(true);
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${jobId}/budget/statement.pdf?${new URLSearchParams({ statement_on: on })}`);
      triggerDownload(blob, "Production Reconciliation.pdf", filename);
    } catch (err) {
      toast(err instanceof Error ? `Couldn't make the statement: ${err.message}` : "Couldn't make the statement.");
    } finally {
      setDownloading(false);
    }
  }

  // Saves go one at a time, and each reads all three fields when it's SENT —
  // not when it was asked for. Tabbing straight through fires three saves; run
  // side by side, an earlier one (sent before the paragraph was typed) could
  // land last and wipe it. Queued, the last to land always holds everything.
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const sent = useRef<Record<string, string> | null>(null);
  function saveAll() {
    queue.current = queue.current.then(() => {
      const value = (k: string) => (document.getElementById(`st-${k}`) as HTMLInputElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
      const now = { client_contact: value("client_contact"), estimate_ref: value("estimate_ref"), intro: value("intro") };
      const last = sent.current ?? { client_contact: statement.client_contact, estimate_ref: statement.estimate_ref, intro: statement.intro };
      if ((["client_contact", "estimate_ref", "intro"] as const).every((k) => now[k] === last[k])) return;
      sent.current = now;
      return onSave(now);
    });
  }

  const field = (key: "client_contact" | "estimate_ref" | "intro", label: string, multi: boolean, placeholder: string) => (
    <div>
      <label htmlFor={`st-${key}`} className="field-label">{label}</label>
      {multi ? (
        <textarea id={`st-${key}`} key={`${key}-${statement.ready}`} defaultValue={statement[key]} rows={key === "intro" ? 3 : 2}
          maxLength={key === "intro" ? 2000 : 600} placeholder={placeholder} className="field-input" disabled={!statement.ready}
          onBlur={saveAll} />
      ) : (
        <input id={`st-${key}`} key={`${key}-${statement.ready}`} defaultValue={statement[key]} maxLength={80}
          placeholder={placeholder} className="field-input" disabled={!statement.ready}
          onBlur={saveAll}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
      )}
    </div>
  );

  return (
    <section className="card p-4 grid gap-3 text-sm" aria-label="Client statement">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-xl">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Client statement</h3>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            A PDF for the client: each line Estimated and This project, with its note as the reason, then the revised total and
            what&apos;s been invoiced. Not an invoice, and nothing about cost or profit is on it.
          </p>
        </div>
        <span className="flex items-center gap-2">
          <DateInput value={on} onChange={setOn} ariaLabel="Statement date" className="field-ghost" />
          <button type="button" className="btn btn-primary btn-sm" disabled={!hasEstimate || downloading || !on} onClick={download}>
            {downloading ? "Preparing…" : "Download PDF"}
          </button>
        </span>
      </div>
      {!statement.ready && (
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          The client contact, estimate number and opening paragraph can&apos;t be saved on this server yet. The statement still downloads.
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-[1fr_12rem]">
        {field("client_contact", "Client contact (one per line)", true, "Name\nCompany")}
        {field("estimate_ref", "Estimate number", false, "EST-1007")}
      </div>
      {field("intro", "What happened, for the client", true, "The project was estimated at six filming days across three markets. Four were shot…")}
    </section>
  );
}

function Summary({ t }: { t: RTotals }) {
  const billed = Math.max(t.billed_cents, 0);
  const pct = (c: number) => (billed > 0 ? `${Math.max(0, Math.min(100, (c / billed) * 100))}%` : "0%");
  const profit = Math.max(t.profit_loss_cents, 0);
  return (
    <section className="card p-4 grid gap-3" aria-label="Where the money went">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
        <span style={{ color: "var(--text-secondary)" }}>Billed <Figure tone="strong">{formatCents(t.billed_cents)}</Figure></span>
        <span style={{ color: "var(--text-secondary)" }}>Cost <Figure>{formatCents(t.cost_cents)}</Figure></span>
        <span style={{ color: "var(--text-secondary)" }}>
          Profit/Loss <Figure tone={signed(t.profit_loss_cents)}>{formatCents(t.profit_loss_cents)}</Figure>
          {t.margin_bp !== null && <DateText muted>{bpToPct(t.margin_bp)}% margin</DateText>}
        </span>
      </div>
      {billed > 0 && (
        <>
          <div className="bill-bar" role="img"
            aria-label={`Of ${formatCents(t.billed_cents)} billed: ${formatCents(t.cost_cents)} cost, ${formatCents(t.unreconciled_cents)} with no cost logged yet, ${formatCents(t.profit_loss_cents)} profit`}>
            <span className="bill-seg-cost" style={{ width: pct(t.cost_cents) }} />
            <span className="bill-seg-unrec" style={{ width: pct(t.unreconciled_cents) }} />
            <span className="bill-seg-profit" style={{ width: pct(profit) }} />
          </div>
          <p className="text-xs flex flex-wrap gap-x-4 gap-y-1" style={{ color: "var(--text-secondary)" }}>
            <span><span className="bill-key bill-seg-cost" />Cost</span>
            {t.unreconciled_cents > 0 && <span><span className="bill-key bill-seg-unrec" />No cost logged yet</span>}
            <span><span className="bill-key bill-seg-profit" />Profit</span>
          </p>
        </>
      )}
      {t.unreconciled_cents > 0 && (
        <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
          <DateText>{formatCents(t.unreconciled_cents)}</DateText> is billed with no cost logged against it yet, so the profit
          above is a ceiling until those invoices land.
        </p>
      )}
    </section>
  );
}

function BucketCard({ title, note, rows }: { title: string; note: string; rows: [string, number, boolean?][] }) {
  return (
    <section className="card p-4 text-sm" aria-label={title}>
      <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{title}</h3>
      <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>{note}</p>
      {rows.map(([label, cents, strong]) => (
        <div key={label} className="flex justify-between gap-3 py-0.5">
          <span style={{ color: "var(--text-secondary)" }}>{label}</span>
          <DateText><span style={{ color: "var(--text-primary)", fontWeight: strong ? 600 : 400 }}>{formatCents(cents)}</span></DateText>
        </div>
      ))}
    </section>
  );
}

function Panel({ title, total, items, note, tone }: { title: string; total: number; items: Named[]; note: string; tone?: "bad" }) {
  return (
    <section className="card p-4 text-sm" aria-label={title}>
      <div className="flex justify-between gap-3">
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{title}</h3>
        <DateText><span style={{ color: tone === "bad" ? "var(--danger)" : "var(--text-primary)", fontWeight: 600 }}>{formatCents(total)}</span></DateText>
      </div>
      <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>{note}</p>
      <ul className="grid gap-0.5 text-xs">
        {items.map((i, n) => (
          <li key={`${i.id}-${n}`} className="flex justify-between gap-3" style={{ color: "var(--text-secondary)" }}>
            <span>{i.name}{i.block ? ` · ${i.block}` : ""}{i.why ? ` · ${i.why}` : ""}</span>
            <DateText>{formatCents(i.cents)}</DateText>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SectionBlock({ name, showHeading, lines, busy, toast, onUpdate }: {
  name: string | null; showHeading: boolean; lines: RLine[]; busy: string | null; toast: (m: string) => void;
  onUpdate: (line: RLine, body: Record<string, unknown>) => void;
}) {
  return (
    <>
      {showHeading && (
        <tr><td colSpan={7} className="text-sm font-semibold" style={{ background: "var(--bg-inset)", color: name ? "var(--text-primary)" : "var(--text-muted)" }}>
          {name ?? "No heading"}
        </td></tr>
      )}
      {lines.map((l) => <Row key={l.id} line={l} busy={busy === l.id} toast={toast} onUpdate={(b) => onUpdate(l, b)} />)}
    </>
  );
}

function Row({ line: l, busy, toast, onUpdate }: {
  line: RLine; busy: boolean; toast: (m: string) => void; onUpdate: (body: Record<string, unknown>) => void;
}) {
  const c = l.calc;
  const blurOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === "Enter") e.currentTarget.blur(); };
  function money(field: "act_cents" | "bill_cents", text: string, current: number | null) {
    const cents = parseCents(text);
    if (cents === undefined) { toast("That isn't an amount."); return; }
    if (cents !== current) onUpdate({ [field]: cents });
  }
  const flag = (label: string, key: "dropped" | "awaiting_cost" | "act_paid" | "cost_final", on: boolean) => (
    <label className="flex items-center gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
      <input type="checkbox" checked={on} disabled={busy} onChange={(e) => onUpdate({ [key]: e.target.checked })} />{label}
    </label>
  );

  return (
    <tr style={{ opacity: l.dropped ? 0.55 : 1 }}>
      <td>
        <span className="grid gap-1">
          <span className="text-sm font-medium" style={{ color: "var(--text-primary)", textDecoration: l.dropped ? "line-through" : undefined }}>
            {l.name}
          </span>
          <input key={`note-${l.id}-${l.note}`} defaultValue={l.note ?? ""} maxLength={4000} disabled={busy}
            placeholder="Reason, for the client statement" aria-label={`Note on ${l.name} for the client statement`}
            className="field-ghost text-xs" style={{ color: "var(--text-secondary)", paddingLeft: 0 }}
            onBlur={(e) => { const v = e.target.value.trim(); if (v !== (l.note ?? "")) onUpdate({ note: v || null }); }}
            onKeyDown={blurOnEnter} />
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {l.block && <span className="custom-pill">{l.block}</span>}
            {l.dropped && <span className="custom-pill">Not shot</span>}
            {c.unquoted && <span className="text-xs" style={{ color: "var(--danger)" }}>Not on the estimate</span>}
            {l.est_cents !== null && flag("Not shot", "dropped", l.dropped)}
            {!l.dropped && l.act_cents === null && l.bucket !== "fee" && flag("Invoice expected", "awaiting_cost", l.awaiting_cost)}
            {!l.dropped && l.act_cents !== null && l.bucket !== "fee" && flag("Paid", "act_paid", l.act_paid)}
            {!l.dropped && l.act_from_expenses && l.bucket !== "fee" && flag("All costs in", "cost_final", !l.act_open)}
          </span>
        </span>
      </td>
      <td>
        <select value={l.bucket} disabled={busy} className="field-ghost" style={{ width: "auto" }} aria-label={`Basis for ${l.name}`}
          onChange={(e) => onUpdate({ bucket: e.target.value })}>
          {BASIS.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
        </select>
      </td>
      <td style={{ textAlign: "right" }}><Figure tone={l.est_cents === null ? "muted" : undefined}>{l.est_cents === null ? "—" : formatCents(l.est_cents)}</Figure></td>
      <td style={{ textAlign: "right" }}>
        {l.bucket === "rate" && !l.dropped && l.est_cents !== null ? (
          <input key={`bill-${l.id}-${l.bill_cents}`} defaultValue={centsToInput(l.bill_cents)} placeholder="as quoted" inputMode="decimal"
            aria-label={`Billing at, for ${l.name}`} title="When the scope moved: what this line bills now. The quote stays as it was."
            className="field-ghost date-text" style={{ width: "11ch", textAlign: "right" }} disabled={busy}
            onBlur={(e) => money("bill_cents", e.target.value, l.bill_cents)} onKeyDown={blurOnEnter} />
        ) : <Figure tone="muted">—</Figure>}
      </td>
      <td style={{ textAlign: "right" }}>
        {l.dropped ? <Figure tone="muted">—</Figure> : l.act_from_expenses ? (
          <span className="grid justify-items-end">
            <Figure>{formatCents(l.act_cents)}</Figure>
            <span className="custom-pill" title="The sum of the PC log receipts pointed at this line">
              {l.expense_count} {l.expense_count === 1 ? "receipt" : "receipts"}{l.act_open && l.bucket !== "fee" ? " so far" : ""}
            </span>
          </span>
        ) : (
          <input key={`act-${l.id}-${l.act_cents}`} defaultValue={centsToInput(l.act_cents)} inputMode="decimal"
            placeholder={l.bucket === "fee" ? "as quoted" : "0.00"} aria-label={`Actual for ${l.name}`}
            title={l.bucket === "fee" ? "What you billed, if the fee changed" : "What it cost"}
            className="field-ghost date-text" style={{ width: "11ch", textAlign: "right" }} disabled={busy}
            onBlur={(e) => money("act_cents", e.target.value, l.act_cents)} onKeyDown={blurOnEnter} />
        )}
      </td>
      <td style={{ textAlign: "right" }}>
        {c.diff_cents === null ? <Figure tone="muted">—</Figure> : <Figure tone={signed(c.diff_cents)}>{formatCents(c.diff_cents)}</Figure>}
      </td>
      <td style={{ textAlign: "right" }}>
        {c.profit_loss_cents !== null ? (
          <Figure tone={signed(c.profit_loss_cents)}>{formatCents(c.profit_loss_cents)}</Figure>
        ) : c.unreconciled_cents > 0 ? (
          <span className="text-xs" style={{ display: "inline-block", padding: "0.375rem 0.5rem", color: "var(--text-muted)" }}>awaiting cost</span>
        ) : <Figure tone="muted">—</Figure>}
      </td>
    </tr>
  );
}

function AddCost({ blocks, busy, toast, onAdd }: {
  blocks: string[]; busy: boolean; toast: (m: string) => void; onAdd: (body: Record<string, unknown>) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [bucket, setBucket] = useState<Bucket>("pass");
  const [market, setMarket] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const cents = parseCents(amount);
    if (!name.trim()) { toast("Say what it was."); return; }
    if (cents === undefined || cents === null) { toast("Enter what it cost, like 54.92."); return; }
    if (await onAdd({ name, act_cents: cents, bucket, block: market.trim() || null })) { setName(""); setAmount(""); }
  }

  return (
    <form className="card p-4 grid gap-3" onSubmit={submit} aria-label="Add a cost that wasn't on the estimate">
      <div>
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Add a cost that wasn&apos;t on the estimate</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>Fuel, inflight wifi, the extra rental. At cost bills it on; Fixed absorbs it.</p>
      </div>
      <div className="grid gap-3 items-end md:grid-cols-[1.5fr_auto_auto_auto_auto]">
        <div>
          <label htmlFor="r-name" className="field-label">What</label>
          <input id="r-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} className="field-input" />
        </div>
        <div>
          <label htmlFor="r-amount" className="field-label">Cost</label>
          <input id="r-amount" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="0.00"
            className="field-input date-text" style={{ width: "10ch" }} />
        </div>
        <div>
          <label htmlFor="r-basis" className="field-label">Basis</label>
          <select id="r-basis" value={bucket} onChange={(e) => setBucket(e.target.value as Bucket)} className="field-input">
            <option value="pass">At cost</option>
            <option value="rate">Fixed</option>
          </select>
        </div>
        <div>
          <label htmlFor="r-market" className="field-label">Market</label>
          <input id="r-market" value={market} onChange={(e) => setMarket(e.target.value)} list="r-markets" placeholder="Whole job"
            maxLength={80} className="field-input" style={{ width: "10ch" }} />
          <datalist id="r-markets">{blocks.map((b) => <option key={b} value={b} />)}</datalist>
        </div>
        <button type="submit" className="btn btn-secondary btn-sm" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
      </div>
    </form>
  );
}

function Cash({ t, jobId }: { t: RTotals; jobId: string }) {
  const row = (label: string, cents: number, strong = false, hint?: string) => (
    <div className="flex justify-between gap-4 py-0.5" title={hint}>
      <span style={{ color: strong ? "var(--text-primary)" : "var(--text-secondary)", fontWeight: strong ? 600 : 400 }}>{label}</span>
      <DateText><span style={{ color: cents < 0 ? "var(--danger)" : "var(--text-primary)", fontWeight: strong ? 600 : 400 }}>{formatCents(cents)}</span></DateText>
    </div>
  );
  return (
    <section className="card p-4 text-sm" aria-label="Cash">
      <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Cash</h3>
      <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
        A different question from profit. Invoices are kept on the <Link href={`/jobs/${jobId}/pc-log`} style={{ color: "var(--accent-text)" }}>PC log</Link>.
      </p>
      <div className="grid gap-x-8 md:grid-cols-2">
        <div>
          {row("Invoiced", t.invoiced_cents)}
          {row("Received", t.received_cents)}
          {row("Left to invoice", t.left_to_invoice_cents, false, "Projected billing, open lines landing on estimate, less what's invoiced")}
        </div>
        <div>
          {row("Cash in hand", t.cash_in_hand_cents, false, "Received, less every cost booked")}
          {row("Still to land", t.committed_cents, false, "Fixed lines with no cost yet, and At cost lines at their estimate")}
          {row("After that lands", t.after_committed_cents, true)}
        </div>
      </div>
    </section>
  );
}
