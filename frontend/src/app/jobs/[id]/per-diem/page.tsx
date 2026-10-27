"use client";

/* Job home, Per diem tab (docs/producer-documents-map.md §1.6): what cash each
 * person gets, day by day, and how it was paid. It's the rooming list's grid
 * with a different rule — every away day is paid, the last one too: the job's
 * shoot-day amount on days they shoot, the other amount on every other day.
 * Who's away is set on the Rooming tab; the amounts on Pre-production.
 *
 * Everything owed is worked out by the API (services/per_diem.py). A click
 * takes a day off or puts it back; nothing is recomputed here.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { DayTypeTag } from "@/components/DayType";
import { useToast } from "@/components/Toast";
import { triggerDownload } from "@/lib/download";
import { DayType, displaySpan } from "@/lib/jobDates";
import { money } from "@/lib/rates";

type Method = "cash" | "venmo" | "zelle" | "check" | "other";
interface Paid { method: Method; date: string | null; note: string | null }
interface Row { hire_id: string; name: string; notes: string; cells: Record<string, number>; total: number; paid: Paid | null; paid_text: string }
interface Sheet {
  dates: { date: string; types: DayType[]; label: string | null }[];
  rows: Row[];
  totals: Record<string, number>;
  total: number;
  missing_amounts: boolean;
  rates: { shoot: string; other: string };
  overrides: Record<string, Record<string, number>>;
}

const METHODS: [Method, string][] = [["cash", "Cash"], ["venmo", "Venmo"], ["zelle", "Zelle"], ["check", "Check"], ["other", "Other"]];

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function PerDiemPage() {
  const { id } = useParams<{ id: string }>();
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<Sheet>(`/api/jobs/${id}/per-diem`).then(setSheet).catch(() => setLoadError(true));
  }, [id]);
  useEffect(load, [load]);

  async function save(hireId: string, body: Record<string, unknown>) {
    setBusy(hireId);
    try {
      await api.put(`/api/jobs/${id}/hires/${hireId}/per-diem`, body);
      setSheet(await api.get<Sheet>(`/api/jobs/${id}/per-diem`));
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that change.");
    } finally {
      setBusy(null);
    }
  }

  // A day with per diem comes off (0); a day taken off comes back. A day
  // they're not away has nothing to restore — that's set on the Rooming tab.
  function clickCell(row: Row, d: string) {
    const o = { ...(sheet?.overrides[row.hire_id] ?? {}) };
    if (row.cells[d]) { if (d in o) delete o[d]; else o[d] = 0; }
    else if (d in o) delete o[d];
    else return;
    save(row.hire_id, { per_diem_overrides: o });
  }

  function setMethod(row: Row, method: string) {
    if (!method) save(row.hire_id, { per_diem_paid: null });
    else save(row.hire_id, { per_diem_paid: { method, date: row.paid?.date ?? today(), note: row.paid?.note ?? null } });
  }

  async function download(kind: "xlsx" | "pdf") {
    setBusy(kind);
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/per-diem/${kind}`);
      triggerDownload(blob, `Per diem.${kind}`, filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download the per diem sheet.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <LoadError message="Couldn't load the per diem sheet." onRetry={load} />;
  if (!sheet) return <TableSkeleton />;

  const paidCount = sheet.rows.filter((r) => r.paid).length;

  return (
    <div>
      {toastNode}

      <div className="flex items-center justify-between gap-4 mb-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Per diem</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {sheet.missing_amounts ? "No per diem amounts on this job yet."
              : <>{sheet.rates.other || "—"} a day away, {sheet.rates.shoot || "—"} on shoot days · every day away is paid, the last one too.</>}{" "}
            Who&apos;s away is set on the <Link href={`/jobs/${id}/rooming`} style={{ color: "var(--accent-text)" }}>Rooming</Link> tab;
            the amounts on <Link href={`/jobs/${id}/pre-production`} style={{ color: "var(--accent-text)" }}>Pre-production</Link>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => download("xlsx")} disabled={!!busy || !sheet.rows.length} className="btn btn-primary btn-sm">
            {busy === "xlsx" ? "Preparing…" : "Download Excel"}
          </button>
          <button type="button" onClick={() => download("pdf")} disabled={!!busy || !sheet.rows.length} className="btn btn-secondary btn-sm">
            {busy === "pdf" ? "Preparing…" : "PDF"}
          </button>
        </div>
      </div>

      {sheet.missing_amounts && (
        <div className="next-step mb-5" role="status">
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span className="next-step-label">Next</span>
            Set the job&apos;s per diem — shoot days and non-shoot days — and everyone away gets a row here.
          </p>
          <Link href={`/jobs/${id}/pre-production`} className="btn btn-primary btn-sm">Set per diem</Link>
        </div>
      )}

      {!sheet.missing_amounts && (
        <>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mb-3 text-sm" style={{ color: "var(--text-secondary)" }}>
            <span><b style={{ color: "var(--text-primary)" }}>{sheet.rows.length}</b> owed per diem</span>
            <span><b className="date-text" style={{ color: "var(--text-primary)" }}>{money(sheet.total) || "$0"}</b> in all</span>
            <span><b style={{ color: "var(--text-primary)" }}>{paidCount}</b> paid</span>
          </div>
          <div className="data-table-raised">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Notes</th>
                  {sheet.dates.map((c) => (
                    <th key={c.date} style={{ textAlign: "center" }}>
                      <span className="grid justify-items-center gap-0.5">
                        <DateText>{displaySpan(c.date, c.date)}</DateText>
                        {c.types.map((t) => <DayTypeTag key={t} type={t} />)}
                        {c.label && <span className="text-xs" style={{ color: "var(--text-secondary)", textTransform: "none", fontWeight: 400 }}>{c.label}</span>}
                      </span>
                    </th>
                  ))}
                  <th style={{ textAlign: "center" }}>Total</th>
                  <th>Paid</th>
                </tr>
              </thead>
              <tbody>
                {sheet.rows.length === 0 && (
                  <tr><td colSpan={sheet.dates.length + 4} className="text-sm" style={{ color: "var(--text-muted)" }}>
                    Nobody&apos;s away, so nobody&apos;s owed per diem. Mark who travels on the Rooming tab.
                  </td></tr>
                )}
                {sheet.rows.map((r) => {
                  const o = sheet.overrides[r.hire_id] ?? {};
                  return (
                    <tr key={r.hire_id}>
                      <td className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{r.name}</td>
                      <td>
                        <input key={r.notes} defaultValue={r.notes} maxLength={200}
                          onBlur={(e) => { if (e.target.value.trim() !== r.notes) save(r.hire_id, { per_diem_note: e.target.value }); }}
                          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                          placeholder="—" aria-label={`Per diem note for ${r.name}`} className="field-ghost" />
                      </td>
                      {sheet.dates.map((c) => {
                        const amount = r.cells[c.date];
                        const off = !amount && c.date in o;
                        return (
                          <td key={c.date} style={{ padding: "0.375rem", textAlign: "center" }}>
                            <button type="button" className="cell-btn" disabled={busy === r.hire_id || (!amount && !off)}
                              onClick={() => clickCell(r, c.date)} style={{ justifyItems: "center" }}
                              aria-label={`${r.name}, ${displaySpan(c.date, c.date)}: ${amount ? `${money(amount)} — click to take this day off` : off ? "taken off — click to put it back" : "not away"}`}>
                              {amount ? <DateText>{money(amount)}</DateText>
                                : off ? <span className="text-xs" style={{ color: "var(--text-muted)", textDecoration: "line-through" }}>off</span>
                                  : <span className="empty">·</span>}
                            </button>
                          </td>
                        );
                      })}
                      <td style={{ textAlign: "center" }}><DateText>{money(r.total)}</DateText></td>
                      <td>
                        <span className="flex items-center gap-1.5">
                          <select value={r.paid?.method ?? ""} onChange={(e) => setMethod(r, e.target.value)} disabled={busy === r.hire_id}
                            aria-label={`How ${r.name} was paid`} className="field-ghost" style={{ width: "6.5rem" }}>
                            <option value="">Not paid</option>
                            {METHODS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                          </select>
                          {r.paid && (
                            <DateInput value={r.paid.date ?? ""} ariaLabel={`Date ${r.name} was paid`} className="field-ghost"
                              onChange={(v) => save(r.hire_id, { per_diem_paid: { ...r.paid!, date: v || null } })} />
                          )}
                        </span>
                      </td>
                    </tr>
                  );
                })}
                {sheet.rows.length > 0 && (
                  <tr>
                    <td className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }} colSpan={2}>Totals</td>
                    {sheet.dates.map((c) => (
                      <td key={c.date} style={{ textAlign: "center" }}><DateText>{sheet.totals[c.date] ? money(sheet.totals[c.date]) : "—"}</DateText></td>
                    ))}
                    <td style={{ textAlign: "center" }}><DateText>{money(sheet.total)}</DateText></td>
                    <td />
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
