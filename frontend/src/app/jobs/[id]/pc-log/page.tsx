"use client";

/* Job home, PC log tab (docs/producer-documents-map.md §1.10): the reconciliation
 * cover sheet — one line per receipt, in the client's nine columns, then the
 * production fee, the advance and what's still owed.
 *
 * Two kinds of line. What she types (a receipt) is hers to edit. GENERATED
 * lines — each booked person's rates × days, the per diem total, every vendor
 * payment — follow the job until the log is marked sent; she can hide one,
 * change its amount or its column, and put it back. "Mark as sent" freezes a
 * copy; the downloads print that copy, and anything that's moved since is
 * listed here, never applied to it.
 *
 * A receipt can be pointed at a line of the estimate; the Budget tab's
 * Reconcile view then takes that line's actual cost as the sum of its receipts.
 *
 * Every figure comes from the API (services/pc_log.py). Nothing is added up here.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { useToast } from "@/components/Toast";
import { triggerDownload } from "@/lib/download";
import { bpToPct, centsToInput, formatCents, parseBp, parseCents } from "@/lib/money";
import { ReadReceipts } from "./ReadReceipts";

type Source = "crew" | "talent" | "per_diem" | "vendor" | "expense";
interface Row {
  key: string; source: Source; number: number | null; spent_on: string | null;
  payee: string; description: string; amount_cents: number; category: string;
  generated: boolean; hidden: boolean; missing_rates: string[];
  expense_id?: string; has_receipt?: boolean; receipt_name?: string | null; budget_line_id?: string | null;
  generated_amount_cents?: number; generated_category?: string;
  amount_overridden?: boolean; category_overridden?: boolean;
}
interface Totals {
  by_category: Record<string, number>; total_cents: number; fee_bp: number; fee_cents: number;
  grand_total_cents: number; advance_cents: number; difference_cents: number;
}
interface Change { key: string; change: "added" | "removed" | "changed"; payee: string; description: string; then_cents?: number | null; now_cents?: number | null }
interface Invoice { id: string; label: string; amount_cents: number; paid: boolean; paid_on: string | null; issued_on: string | null }
interface Log {
  migrated: boolean;
  header: { job_name: string; producer: string; project_dates: string; client: string };
  rows: Row[]; totals: Totals;
  settings: { production_fee_bp: number; pc_log_camera: "photography" | "video" };
  invoices: Invoice[];
  sent: { id: string; sent_on: string } | null;
  sends: { id: string; sent_on: string }[];
  changes: Change[];
  categories: Record<string, string>;
  budget_lines?: BudgetLine[];
}
interface BudgetLine { id: string; name: string; section: string | null; block: string | null; dropped: boolean }

const SOURCE_LABEL: Record<Source, string> = {
  crew: "From rates", talent: "From rates", per_diem: "From per diem", vendor: "From vendors", expense: "",
};

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** "travel", "shoot or travel", "prep, travel or wrap". */
function listWords(words: string[]): string {
  return words.length < 2 ? words.join("") : `${words.slice(0, -1).join(", ")} or ${words[words.length - 1]}`;
}

function shortDate(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${m}/${d}/${String(y % 100).padStart(2, "0")}`;
}

export default function PcLogPage() {
  const { id } = useParams<{ id: string }>();
  const [log, setLog] = useState<Log | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [sendDate, setSendDate] = useState(today());
  const [sending, setSending] = useState(false);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    return api.get<Log>(`/api/jobs/${id}/pc-log`).then(setLog).catch(() => setLoadError(true));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  /** One write, then the log as the API now works it out. */
  async function run(tag: string, write: () => Promise<unknown>, done?: string) {
    setBusy(tag);
    try {
      const out = await write();
      if (out && typeof out === "object" && "rows" in (out as object)) setLog(out as Log);
      else setLog(await api.get<Log>(`/api/jobs/${id}/pc-log`));
      if (done) showToast(done);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that change.");
      load();
    } finally {
      setBusy(null);
    }
  }

  // A generated line's hand changes, sent whole each time.
  function override(row: Row, patch: { hidden?: boolean; amount_cents?: number | null; category?: string | null }) {
    const body = {
      hidden: patch.hidden ?? row.hidden,
      amount_cents: "amount_cents" in patch ? patch.amount_cents : row.amount_overridden ? row.amount_cents : null,
      category: "category" in patch ? patch.category : row.category_overridden ? row.category : null,
    };
    if (body.amount_cents === row.generated_amount_cents) body.amount_cents = null;
    if (body.category === row.generated_category) body.category = null;
    return run(row.key, () => api.put(`/api/jobs/${id}/pc-log/generated/${encodeURIComponent(row.key)}`, body));
  }

  function updateExpense(row: Row, body: Record<string, unknown>) {
    return run(row.key, () => api.put(`/api/jobs/${id}/expenses/${row.expense_id}`, body));
  }

  function setAmount(row: Row, text: string) {
    const cents = parseCents(text);
    if (cents === undefined) { showToast("That isn't an amount."); return; }
    if (cents === row.amount_cents) return;
    if (row.generated) override(row, { amount_cents: cents });
    else if (cents !== null) updateExpense(row, { amount_cents: cents });
  }

  // Opened in a new tab: the window opens on the click (so no popup blocker
  // objects), then gets the file once it has arrived.
  async function viewReceipt(row: Row) {
    const w = window.open("", "_blank");
    try {
      const { blob } = await downloadFile(`/api/jobs/${id}/expenses/${row.expense_id}/receipt`);
      const url = URL.createObjectURL(blob);
      if (w) w.location.href = url; else window.location.href = url;
    } catch (err) {
      w?.close();
      showToast(err instanceof Error ? `Couldn't open the receipt: ${err.message}` : "Couldn't open the receipt.");
    }
  }

  async function download(kind: "xlsx" | "pdf", sendId?: string) {
    setBusy(kind + (sendId ?? ""));
    try {
      const q = sendId ? `?send_id=${sendId}` : "";
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/pc-log/${kind}${q}`);
      triggerDownload(blob, `PC Log.${kind}`, filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download the PC log.");
    } finally {
      setBusy(null);
    }
  }

  async function markSent() {
    setSending(true);
    await run("send", () => api.post(`/api/jobs/${id}/pc-log/send`, { sent_on: sendDate || null }), "Marked as sent. The downloads print this version.");
    setSending(false);
  }

  if (loadError) return <LoadError message="Couldn't load the PC log." onRetry={load} />;
  if (!log) return <TableSkeleton />;

  const cats = Object.entries(log.categories);
  const shown = log.rows.filter((r) => !r.hidden);
  const hidden = log.rows.filter((r) => r.hidden);
  const t = log.totals;

  return (
    <div>
      {toastNode}

      <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>PC log</h2>
          <p className="text-xs max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            One line per receipt, in the client&apos;s columns. Fees, per diem and vendor payments are worked out from the
            job — rates on <Link href={`/jobs/${id}/pre-production`} style={{ color: "var(--accent-text)" }}>Pre-production</Link>,
            payments on <Link href={`/jobs/${id}/vendors`} style={{ color: "var(--accent-text)" }}>Vendors</Link> — and follow it until you mark the log sent.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => download("xlsx")} disabled={!!busy || !shown.length} className="btn btn-primary btn-sm">
            {busy === "xlsx" ? "Preparing…" : "Download Excel"}
          </button>
          <button type="button" onClick={() => download("pdf")} disabled={!!busy || !shown.length} className="btn btn-secondary btn-sm">
            {busy === "pdf" ? "Preparing…" : "PDF"}
          </button>
        </div>
      </div>

      {!log.migrated && (
        <div className="next-step mb-5" role="status">
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span className="next-step-label">Not set up</span>
            This server doesn&apos;t have the PC log tables yet, so the lines below can&apos;t be saved or sent.
          </p>
        </div>
      )}

      <SentStatus log={log} sendDate={sendDate} setSendDate={setSendDate} sending={sending} busy={!!busy}
        disabled={!log.migrated || !shown.length} onSend={markSent} onDownload={download} />

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 mb-3 text-sm" style={{ color: "var(--text-secondary)" }}>
        <label className="flex items-center gap-1.5">
          Production fee
          <input key={`fee-${t.fee_bp}`} defaultValue={bpToPct(t.fee_bp)} inputMode="decimal" disabled={!log.migrated}
            aria-label="Production fee percent" className="field-ghost date-text" style={{ width: "5ch", textAlign: "right" }}
            onBlur={(e) => {
              const bp = parseBp(e.target.value);
              if (bp === undefined) { showToast("The fee is a percent between 0 and 100."); e.target.value = bpToPct(t.fee_bp); return; }
              if (bp !== t.fee_bp) run("settings", () => api.put(`/api/jobs/${id}/pc-log/settings`, { production_fee_bp: bp }));
            }}
            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />%
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>of fees and expenses</span>
        </label>
        <label className="flex items-center gap-1.5">
          Camera team bills as
          <select value={log.settings.pc_log_camera} disabled={!log.migrated || !!busy} className="field-ghost" style={{ width: "auto" }}
            onChange={(e) => run("settings", () => api.put(`/api/jobs/${id}/pc-log/settings`, { pc_log_camera: e.target.value }))}>
            <option value="photography">Photography</option>
            <option value="video">Video</option>
          </select>
        </label>
      </div>

      <div className="data-table-raised mb-4">
        <table>
          <thead>
            <tr>
              <th style={{ width: "3rem" }}>#</th>
              <th>Date</th>
              <th>To whom paid</th>
              <th style={{ minWidth: "16rem" }}>For what</th>
              <th>Column</th>
              <th style={{ textAlign: "right" }}>Total</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={7} className="text-sm" style={{ color: "var(--text-muted)" }}>
                Nothing on the log yet. Add a receipt below, or set rates on Pre-production and payments on Vendors.
              </td></tr>
            )}
            {shown.map((r) => (
              <tr key={r.key}>
                <td><DateText>{r.number}</DateText></td>
                <td>
                  {r.generated ? <DateText>{shortDate(r.spent_on) || "—"}</DateText> : (
                    <DateInput value={r.spent_on ?? ""} ariaLabel={`Date of ${r.payee || "this receipt"}`} className="field-ghost"
                      onChange={(v) => updateExpense(r, { spent_on: v || null })} />
                  )}
                </td>
                <td>
                  {r.generated ? (
                    <span className="grid gap-0.5">
                      <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{r.payee}</span>
                      <span><span className="custom-pill">{SOURCE_LABEL[r.source]}</span></span>
                    </span>
                  ) : (
                    <span className="grid gap-0.5">
                      <input key={`p-${r.key}-${r.payee}`} defaultValue={r.payee} maxLength={200} placeholder="To whom paid"
                        aria-label="To whom paid" className="field-ghost"
                        onBlur={(e) => { if (e.target.value.trim() !== r.payee) updateExpense(r, { payee: e.target.value }); }}
                        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
                      {r.has_receipt && (
                        <span><button type="button" className="custom-pill" onClick={() => viewReceipt(r)}
                          title={r.receipt_name ?? undefined} aria-label={`Open the receipt for ${r.payee || "this line"}`}>Receipt</button></span>
                      )}
                    </span>
                  )}
                </td>
                <td>
                  {r.generated ? (
                    <span className="grid gap-0.5">
                      <span className="text-sm" style={{ color: "var(--text-secondary)" }}>{r.description}</span>
                      {r.missing_rates.length > 0 && (
                        <span className="text-xs" style={{ color: "var(--warning)" }}>
                          {`No ${listWords(r.missing_rates)} rate set — those days aren't counted`}
                        </span>
                      )}
                    </span>
                  ) : (
                    <span className="grid gap-0.5">
                      <input key={`d-${r.key}-${r.description}`} defaultValue={r.description} maxLength={500} placeholder="For what"
                        aria-label={`What ${r.payee || "this receipt"} was for`} className="field-ghost"
                        onBlur={(e) => { if (e.target.value.trim() !== r.description) updateExpense(r, { description: e.target.value }); }}
                        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
                      {!!log.budget_lines?.length && (
                        <BudgetLinePicker lines={log.budget_lines} value={r.budget_line_id ?? null} disabled={busy === r.key}
                          label={r.payee || "this receipt"} onChange={(v) => updateExpense(r, { budget_line_id: v })} />
                      )}
                    </span>
                  )}
                </td>
                <td>
                  <span className="flex items-center gap-1.5">
                    <select value={r.category} disabled={busy === r.key || !log.migrated} className="field-ghost" style={{ width: "auto" }}
                      aria-label={`Column for ${r.payee}`}
                      onChange={(e) => r.generated ? override(r, { category: e.target.value }) : updateExpense(r, { category: e.target.value })}>
                      {cats.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                    {r.category_overridden && <span className="custom-pill">moved</span>}
                  </span>
                </td>
                <td style={{ textAlign: "right" }}>
                  <span className="flex items-center justify-end gap-1.5">
                    {r.amount_overridden && <span className="custom-pill" title={`Worked out: ${formatCents(r.generated_amount_cents)}`}>edited</span>}
                    <input key={`a-${r.key}-${r.amount_cents}`} defaultValue={centsToInput(r.amount_cents)} inputMode="decimal"
                      disabled={busy === r.key || !log.migrated} aria-label={`Amount for ${r.payee}`}
                      className="field-ghost date-text" style={{ width: "10ch", textAlign: "right" }}
                      onBlur={(e) => setAmount(r, e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
                  </span>
                </td>
                <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                  {r.generated ? (
                    <>
                      {(r.amount_overridden || r.category_overridden) && (
                        <button type="button" className="btn btn-ghost btn-sm" disabled={busy === r.key}
                          onClick={() => override(r, { amount_cents: null, category: null })}>Reset</button>
                      )}
                      <button type="button" className="btn btn-remove" disabled={busy === r.key || !log.migrated}
                        onClick={() => override(r, { hidden: true })} aria-label={`Take ${r.payee} off the log`}>Hide</button>
                    </>
                  ) : confirmRemove === r.key ? (
                    <>
                      <button type="button" className="btn btn-sm btn-confirm-remove" disabled={busy === r.key}
                        onClick={async () => { await run(r.key, () => api.delete(`/api/jobs/${id}/expenses/${r.expense_id}`), "Receipt removed."); setConfirmRemove(null); }}>
                        Remove this receipt
                      </button>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmRemove(null)}>Cancel</button>
                    </>
                  ) : (
                    <button type="button" className="btn btn-remove" onClick={() => setConfirmRemove(r.key)}
                      aria-label={`Remove ${r.payee || "this receipt"}`}>Remove</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden.length > 0 && (
        <div className="text-sm mb-4 flex flex-wrap items-center gap-2" style={{ color: "var(--text-secondary)" }}>
          <span>Taken off the log:</span>
          {hidden.map((r) => (
            <button key={r.key} type="button" className="btn btn-ghost btn-sm" disabled={busy === r.key}
              onClick={() => override(r, { hidden: false })} aria-label={`Put ${r.payee} back on the log`}>
              {r.payee} <DateText>{formatCents(r.amount_cents)}</DateText> · Show
            </button>
          ))}
        </div>
      )}

      {log.migrated && <ReadReceipts jobId={id} cats={cats} toast={showToast} onAdded={() => api.get<Log>(`/api/jobs/${id}/pc-log`).then(setLog)} />}

      {log.migrated && <AddExpense cats={cats} busy={busy === "add"} onAdd={(body) => run("add", () => api.post(`/api/jobs/${id}/expenses`, body), "Receipt added.")} />}

      <div className="grid gap-4 md:grid-cols-2">
        <Footer log={log} />
        <Invoices log={log} busy={busy} migrated={log.migrated}
          onAdd={(body) => run("invoice", () => api.post(`/api/jobs/${id}/invoices`, body), "Invoice added.")}
          onUpdate={(inv, body) => run(inv.id, () => api.put(`/api/jobs/${id}/invoices/${inv.id}`, body))}
          onRemove={(inv) => run(inv.id, () => api.delete(`/api/jobs/${id}/invoices/${inv.id}`), "Invoice removed.")} />
      </div>
    </div>
  );
}

/** Which line of the estimate a receipt counts against (Budget → Reconcile). */
function BudgetLinePicker({ lines, value, disabled, label, onChange }: {
  lines: BudgetLine[]; value: string | null; disabled: boolean; label: string; onChange: (v: string | null) => void;
}) {
  const sections: (string | null)[] = [];
  for (const l of lines) if (!sections.includes(l.section || null)) sections.push(l.section || null);
  const option = (l: BudgetLine) => (
    <option key={l.id} value={l.id}>{l.name}{l.block ? ` · ${l.block}` : ""}{l.dropped ? " (not shot)" : ""}</option>
  );
  return (
    <select value={value ?? ""} disabled={disabled} className="field-ghost text-xs"
      style={{ width: "auto", maxWidth: "100%", color: value ? "var(--text-secondary)" : "var(--text-muted)" }}
      aria-label={`Estimate line for ${label}`} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">Not against an estimate line</option>
      {sections.length > 1 || sections[0]
        ? sections.map((s) => (
          <optgroup key={s ?? ""} label={s ?? "No heading"}>{lines.filter((l) => (l.section || null) === s).map(option)}</optgroup>
        ))
        : lines.map(option)}
    </select>
  );
}

function SentStatus({ log, sendDate, setSendDate, sending, busy, disabled, onSend, onDownload }: {
  log: Log; sendDate: string; setSendDate: (v: string) => void; sending: boolean; busy: boolean; disabled: boolean;
  onSend: () => void; onDownload: (kind: "xlsx" | "pdf", sendId?: string) => void;
}) {
  const n = log.changes.length;
  const earlier = log.sends.slice(0, -1);
  return (
    <div className="card p-4 mb-5 grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm" style={{ color: "var(--text-primary)" }}>
          {log.sent ? (
            <>Sent <DateText>{shortDate(log.sent.sent_on)}</DateText>. The downloads print that version.
              {n === 0 && <span style={{ color: "var(--text-secondary)" }}> Nothing has changed since.</span>}</>
          ) : (
            <>Not sent yet. Fees, per diem and vendor payments follow the job until you mark it sent.</>
          )}
        </p>
        <span className="flex items-center gap-2">
          <DateInput value={sendDate} ariaLabel="Date the PC log was sent" className="field-ghost" onChange={setSendDate} />
          <button type="button" className={`btn btn-sm ${log.sent && n === 0 ? "btn-secondary" : "btn-primary"}`}
            disabled={disabled || busy || sending} onClick={onSend}>
            {sending ? "Saving…" : log.sent ? "Mark as sent again" : "Mark as sent"}
          </button>
        </span>
      </div>
      {n > 0 && (
        <div className="rounded-md p-3 text-sm" style={{ background: "var(--warning-subtle)", color: "var(--text-primary)" }} role="status">
          <p className="font-medium mb-1">{n} {n === 1 ? "change" : "changes"} since you sent this — not on the copy that went out:</p>
          <ul className="grid gap-0.5" style={{ color: "var(--text-secondary)" }}>
            {log.changes.map((c) => (
              <li key={c.key}>
                {c.change === "added" ? "Added" : c.change === "removed" ? "Removed" : "Changed"}: {[c.payee, c.description].filter(Boolean).join(" — ")}{" "}
                <DateText>
                  {c.change === "added" ? formatCents(c.now_cents) : c.change === "removed" ? formatCents(c.then_cents)
                    : c.then_cents !== c.now_cents ? `${formatCents(c.then_cents)} → ${formatCents(c.now_cents)}` : ""}
                </DateText>
              </li>
            ))}
          </ul>
          <p className="text-xs mt-1.5" style={{ color: "var(--text-secondary)" }}>Mark as sent again to send the update; the earlier version is kept.</p>
        </div>
      )}
      {earlier.length > 0 && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Earlier versions:{" "}
          {earlier.map((s, i) => (
            <span key={s.id}>
              {i > 0 && " · "}
              <DateText>{shortDate(s.sent_on)}</DateText>{" "}
              <button type="button" className="underline" onClick={() => onDownload("xlsx", s.id)} style={{ color: "var(--accent-text)" }}>Excel</button>{" "}
              <button type="button" className="underline" onClick={() => onDownload("pdf", s.id)} style={{ color: "var(--accent-text)" }}>PDF</button>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

function AddExpense({ cats, busy, onAdd }: {
  cats: [string, string][]; busy: boolean; onAdd: (body: Record<string, unknown>) => Promise<void>;
}) {
  const [spentOn, setSpentOn] = useState(today());
  const [payee, setPayee] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("production_misc");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const cents = parseCents(amount);
    if (cents === undefined || cents === null) { setError("Enter the amount, like 84.50."); return; }
    setError(null);
    await onAdd({ spent_on: spentOn || null, payee, description, amount_cents: cents, category });
    setPayee(""); setDescription(""); setAmount("");
  }

  return (
    <form className="card p-4 mb-5 grid gap-3" onSubmit={submit} aria-label="Add a receipt">
      <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Add a receipt</h3>
      <div className="grid gap-3 md:grid-cols-[auto_1fr_1.5fr_auto_auto_auto] items-end">
        <div>
          <span className="field-label">Date</span>
          <DateInput value={spentOn} ariaLabel="Receipt date" className="field-input" onChange={setSpentOn} />
        </div>
        <div>
          <label htmlFor="x-payee" className="field-label">To whom paid</label>
          <input id="x-payee" value={payee} onChange={(e) => setPayee(e.target.value)} maxLength={200} className="field-input" />
        </div>
        <div>
          <label htmlFor="x-what" className="field-label">For what</label>
          <input id="x-what" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} className="field-input" />
        </div>
        <div>
          <label htmlFor="x-amount" className="field-label">Amount</label>
          <input id="x-amount" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="0.00"
            className="field-input date-text" style={{ width: "10ch" }} required />
        </div>
        <div>
          <label htmlFor="x-cat" className="field-label">Column</label>
          <select id="x-cat" value={category} onChange={(e) => setCategory(e.target.value)} className="field-input">
            {cats.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
      </div>
      {error && <p className="text-xs" style={{ color: "var(--danger)" }} role="alert">{error}</p>}
    </form>
  );
}

function Footer({ log }: { log: Log }) {
  const t = log.totals;
  const line = (label: string, cents: number, strong = false) => (
    <div className="flex justify-between gap-4 py-1" style={{ borderTop: strong ? "1px solid var(--border)" : undefined }}>
      <span style={{ color: strong ? "var(--text-primary)" : "var(--text-secondary)", fontWeight: strong ? 600 : 400 }}>{label}</span>
      <DateText><span style={{ color: "var(--text-primary)", fontWeight: strong ? 600 : 400 }}>{formatCents(cents)}</span></DateText>
    </div>
  );
  return (
    <section className="card p-4 text-sm" aria-label="Totals">
      <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>Totals</h3>
      {Object.entries(log.categories).filter(([k]) => t.by_category[k]).map(([k, label]) => (
        <div key={k} className="flex justify-between gap-4 py-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
          <span>{label}</span><DateText>{formatCents(t.by_category[k])}</DateText>
        </div>
      ))}
      <div className="mt-2">
        {line("Total fees and expenses", t.total_cents, true)}
        {line(`Production fee ${bpToPct(t.fee_bp)}%`, t.fee_cents)}
        {line("Grand total", t.grand_total_cents, true)}
        {line("Less advance received", t.advance_cents)}
        {line("Difference", t.difference_cents, true)}
      </div>
    </section>
  );
}

function Invoices({ log, busy, migrated, onAdd, onUpdate, onRemove }: {
  log: Log; busy: string | null; migrated: boolean;
  onAdd: (body: Record<string, unknown>) => Promise<void>;
  onUpdate: (inv: Invoice, body: Record<string, unknown>) => Promise<void>;
  onRemove: (inv: Invoice) => Promise<void>;
}) {
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [paid, setPaid] = useState(true);
  const [confirm, setConfirm] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const cents = parseCents(amount);
    if (cents === undefined || cents === null) return;
    // "Advance" is the placeholder, and what a blank label means.
    await onAdd({ label: label.trim() || "Advance", amount_cents: cents, paid, paid_on: paid ? today() : null });
    setAmount(""); setLabel("");
  }

  return (
    <section className="card p-4 text-sm" aria-label="Invoices and advance">
      <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Invoices</h3>
      <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>What&apos;s been paid is the log&apos;s &ldquo;less advance received&rdquo;.</p>
      {log.invoices.length === 0 && <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>No invoices yet.</p>}
      {log.invoices.map((inv) => (
        <div key={inv.id} className="flex items-center justify-between gap-2 py-1">
          <span style={{ color: "var(--text-primary)" }}>{inv.label}</span>
          <span className="flex items-center gap-2">
            <DateText>{formatCents(inv.amount_cents)}</DateText>
            <select value={inv.paid ? "paid" : "sent"} disabled={busy === inv.id} className="field-ghost" style={{ width: "auto" }}
              aria-label={`Is ${inv.label} paid`}
              onChange={(e) => onUpdate(inv, { paid: e.target.value === "paid", paid_on: e.target.value === "paid" ? today() : null })}>
              <option value="paid">Paid</option>
              <option value="sent">Not paid yet</option>
            </select>
            {confirm === inv.id ? (
              <>
                <button type="button" className="btn btn-sm btn-confirm-remove" disabled={busy === inv.id}
                  onClick={async () => { await onRemove(inv); setConfirm(null); }}>Remove</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm(null)}>Cancel</button>
              </>
            ) : (
              <button type="button" className="btn btn-remove" onClick={() => setConfirm(inv.id)} aria-label={`Remove ${inv.label}`}>Remove</button>
            )}
          </span>
        </div>
      ))}
      {migrated && (
        <form className="flex flex-wrap items-end gap-2 mt-2" onSubmit={submit} aria-label="Add an invoice">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Advance" aria-label="Invoice" maxLength={200}
            className="field-input" style={{ flex: "1 1 8rem" }} />
          <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" inputMode="decimal" aria-label="Invoice amount"
            className="field-input date-text" style={{ width: "10ch" }} />
          <select value={paid ? "paid" : "sent"} onChange={(e) => setPaid(e.target.value === "paid")} className="field-input" style={{ width: "auto" }}
            aria-label="Paid yet">
            <option value="paid">Paid</option>
            <option value="sent">Not paid yet</option>
          </select>
          <button type="submit" className="btn btn-secondary btn-sm" disabled={busy === "invoice"}>{busy === "invoice" ? "Adding…" : "Add"}</button>
        </form>
      )}
    </section>
  );
}
