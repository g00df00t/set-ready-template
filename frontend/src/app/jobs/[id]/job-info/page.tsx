"use client";

/* Job home, Job info tab — what's left of the producer's Job Info Sheet
 * (docs/producer-documents-map.md §1.9) once vendors have their own tab: the four
 * usage dates, and the job's contact sheet — crew, talent, client & agency,
 * vendors — which she used to fill by copying and pasting. Here it's a view:
 * every row reads where the person already lives, and Excel copies it out.
 *
 * Producer-only: it has everyone's phone and email.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateInput } from "@/components/DateInput";
import { DateText } from "@/components/DateText";
import { useToast } from "@/components/Toast";
import { triggerDownload } from "@/lib/download";
import { displaySpan } from "@/lib/jobDates";

type UsageKey = "first_use" | "launch" | "print_expiry" | "web_expiry";
interface Person { hire_id: string; name: string; role: string; phone: string; email: string; first: string | null; last: string | null; status: string }
interface TalentRow extends Person { segment: string; agency: string; agent: string; agent_phone: string; agent_email: string }
interface Info {
  usage_dates: Partial<Record<UsageKey, string>>;
  usage_labels: Record<UsageKey, string>;
  crew: Person[];
  talent: TalentRow[];
  clients: { name: string; organization: string; role: string; phone: string; email: string }[];
  vendors: { kind: string; title: string; name: string; phone: string; email: string }[];
}

function dates(p: Person) {
  return p.first ? <DateText>{displaySpan(p.first, p.last ?? p.first)}</DateText> : <span style={{ color: "var(--text-muted)" }}>—</span>;
}

function Empty({ cols, text }: { cols: number; text: string }) {
  return <tr><td colSpan={cols} className="text-sm" style={{ color: "var(--text-muted)" }}>{text}</td></tr>;
}

export default function JobInfoPage() {
  const { id } = useParams<{ id: string }>();
  const [info, setInfo] = useState<Info | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<Info>(`/api/jobs/${id}/job-info`).then(setInfo).catch(() => setLoadError(true));
  }, [id]);
  useEffect(load, [load]);

  async function setUsage(key: UsageKey, value: string) {
    if (!info) return;
    const next = { ...info.usage_dates, [key]: value || undefined };
    setInfo({ ...info, usage_dates: next });
    try {
      await api.put(`/api/jobs/${id}/usage-dates`, { usage_dates: next });
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save the date.");
      load();
    }
  }

  async function download() {
    setBusy("xlsx");
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/job-info/xlsx`);
      triggerDownload(blob, "Job info.xlsx", filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download the contact sheet.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <LoadError message="Couldn't load the job info." onRetry={load} />;
  if (!info) return <TableSkeleton />;

  const usageKeys = Object.keys(info.usage_labels) as UsageKey[];

  return (
    <div>
      {toastNode}

      <section className="card p-5 mb-6" aria-labelledby="usage-heading">
        <h2 id="usage-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Usage</h2>
        <p className="text-xs mt-0.5 mb-3" style={{ color: "var(--text-secondary)" }}>For your reference — these go on no document.</p>
        <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
          {usageKeys.map((k) => (
            <div key={k}>
              <label htmlFor={`usage-${k}`} className="field-label">{info.usage_labels[k]}</label>
              <DateInput id={`usage-${k}`} value={info.usage_dates[k] ?? ""} onChange={(v) => setUsage(k, v)}
                ariaLabel={info.usage_labels[k]} className="field-input" />
            </div>
          ))}
        </div>
      </section>

      <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Contact sheet</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Everyone on the job, read from where they already live — hires, each day&apos;s client contacts, and Vendors.
            Change a detail there and it changes here.
          </p>
        </div>
        <button type="button" onClick={download} disabled={!!busy} className="btn btn-primary btn-sm">
          {busy === "xlsx" ? "Preparing…" : "Download Excel"}
        </button>
      </div>

      <h3 className="day-label mt-5 mb-2">Crew</h3>
      <div className="data-table-raised mb-6">
        <table>
          <thead><tr><th>Role</th><th>Name</th><th>Cell</th><th>Email</th><th>Travel to travel</th></tr></thead>
          <tbody>
            {info.crew.length === 0 && <Empty cols={5} text="No crew hired yet." />}
            {info.crew.map((p) => (
              <tr key={p.hire_id}>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{p.role || "—"}</td>
                <td className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  {p.name}{p.status && <span className="text-xs ml-2" style={{ color: "var(--accent-text)" }}>{p.status}</span>}
                </td>
                <td><DateText>{p.phone || "—"}</DateText></td>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{p.email || "—"}</td>
                <td>{dates(p)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="day-label mb-2">Talent</h3>
      <div className="data-table-raised mb-6">
        <table>
          <thead><tr><th>Name</th><th>Cell</th><th>Email</th><th>Travel to travel</th><th>Agency · agent</th></tr></thead>
          <tbody>
            {info.talent.length === 0 && <Empty cols={5} text="No talent hired yet." />}
            {info.talent.map((p) => (
              <tr key={p.hire_id}>
                <td className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  {p.name}{p.status && <span className="text-xs ml-2" style={{ color: "var(--accent-text)" }}>{p.status}</span>}
                  {p.segment && <span className="block text-xs font-normal" style={{ color: "var(--text-secondary)" }}>{p.segment}</span>}
                </td>
                <td><DateText>{p.phone || "—"}</DateText></td>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{p.email || "—"}</td>
                <td>{dates(p)}</td>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {[p.agency, p.agent].filter(Boolean).join(" · ") || "—"}
                  {(p.agent_phone || p.agent_email) && (
                    <span className="block text-xs" style={{ color: "var(--text-muted)" }}>{[p.agent_phone, p.agent_email].filter(Boolean).join(" · ")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="day-label mb-2">Client &amp; agency</h3>
      <div className="data-table-raised mb-6">
        <table>
          <thead><tr><th>Organization</th><th>Name</th><th>Role</th><th>Cell</th><th>Email</th></tr></thead>
          <tbody>
            {info.clients.length === 0 && <Empty cols={5} text="No client or agency contacts on this job's days yet." />}
            {info.clients.map((c, i) => (
              <tr key={i}>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{c.organization || "—"}</td>
                <td className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{c.name}</td>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{c.role || "—"}</td>
                <td><DateText>{c.phone || "—"}</DateText></td>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{c.email || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="day-label mb-2">Vendors</h3>
      <div className="data-table-raised">
        <table>
          <thead><tr><th>Kind</th><th>Vendor</th><th>Contact</th><th>Cell</th><th>Email</th></tr></thead>
          <tbody>
            {info.vendors.length === 0 && <Empty cols={5} text="No vendor contacts yet — add them on the Vendors tab." />}
            {info.vendors.map((v, i) => (
              <tr key={i}>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{v.kind}</td>
                <td className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{v.title}</td>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{v.name || "—"}</td>
                <td><DateText>{v.phone || "—"}</DateText></td>
                <td className="text-sm" style={{ color: "var(--text-secondary)" }}>{v.email || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
