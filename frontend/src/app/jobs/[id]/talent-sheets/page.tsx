"use client";

/* Job home, Talent sheets tab (docs/producer-documents-map.md §1.8): the call
 * sheet each talent's agent gets before travel — one per talent, covering all
 * their days: date lines, flights, hotel nights, each shoot day's call time,
 * location, meals and weather, who to call, and prep instructions.
 *
 * Most of it comes from the rest of the job. What's set here is what only
 * this sheet says: which crew an agent may call (you're always first), the
 * hotel billing note, prep instructions, anything else. Downloads only — she
 * sends them herself. Nothing is worked out here; the API names what's missing.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, downloadFile } from "@/lib/api";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateText } from "@/components/DateText";
import { useToast } from "@/components/Toast";
import { triggerDownload } from "@/lib/download";
import { displaySpan } from "@/lib/jobDates";

interface Settings { contacts: string[]; hotel_note: string | null; prep_note: string | null; notes: string | null }
interface Talent { hire_id: string; name: string; role: string | null; shoot_dates: (string | null)[]; gaps: string[] }
interface Crew { hire_id: string; name: string; role: string | null; has_phone: boolean }
interface Panel { settings: Settings; talent: Talent[]; held: string[]; crew: Crew[]; producer_phone: string | null }

export default function TalentSheetsPage() {
  const { id } = useParams<{ id: string }>();
  const [panel, setPanel] = useState<Panel | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [dirty, setDirty] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<Panel>(`/api/jobs/${id}/talent-sheets`)
      .then((p) => { setPanel(p); setDraft(p.settings); setDirty(false); })
      .catch(() => setLoadError(true));
  }, [id]);
  useEffect(load, [load]);

  function edit(patch: Partial<Settings>) {
    setDraft((d) => (d ? { ...d, ...patch } : d));
    setDirty(true);
  }

  function toggleContact(hireId: string) {
    if (!draft) return;
    const on = draft.contacts.includes(hireId);
    edit({ contacts: on ? draft.contacts.filter((c) => c !== hireId) : [...draft.contacts, hireId] });
  }

  async function save() {
    if (!draft) return;
    setBusy("save");
    try {
      await api.put(`/api/jobs/${id}/talent-sheets/settings`, { talent_sheet: draft });
      const p = await api.get<Panel>(`/api/jobs/${id}/talent-sheets`);
      setPanel(p); setDraft(p.settings); setDirty(false);
      showToast("Saved — every talent sheet will say this");
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save.");
    } finally {
      setBusy(null);
    }
  }

  async function download(path: string, key: string, fallback: string) {
    setBusy(key);
    try {
      const { blob, filename } = await downloadFile(`/api/jobs/${id}/talent-sheets/${path}`);
      triggerDownload(blob, fallback, filename);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't download: ${err.message}` : "Couldn't download that.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <LoadError message="Couldn't load the talent sheets." onRetry={load} />;
  if (!panel || !draft) return <TableSkeleton />;

  return (
    <div>
      {toastNode}

      <div className="flex items-start justify-between gap-4 mb-5 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Talent sheets</h2>
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
            One call sheet per talent for their agent, covering all their days. Dates, flights, hotel and each shoot
            day come from the rest of the job; no rates or fees go on it.
          </p>
        </div>
        <button type="button" className="btn btn-primary btn-sm" disabled={!!busy || dirty || !panel.talent.length}
          onClick={() => download("zip", "zip", "Talent call sheets.zip")}
          aria-label={dirty ? "Download all talent sheets — save your changes first" : "Download all talent sheets"}>
          {busy === "zip" ? "Preparing…" : "Download all"}
        </button>
      </div>

      {panel.talent.length === 0 && (
        <div className="next-step mb-5" role="status">
          <p className="text-sm" style={{ color: "var(--text-primary)" }}>
            <span className="next-step-label">Next</span>
            {panel.held.length ? "Confirm a talent hold and their sheet appears here." : "Hire talent on Pre-production, then put them on a shoot day."}
          </p>
          <Link href={`/jobs/${id}/pre-production`} className="btn btn-primary btn-sm">Go to Pre-production</Link>
        </div>
      )}

      {panel.talent.length > 0 && (
        <div className="data-table-raised mb-6">
          <table>
            <thead>
              <tr><th>Talent</th><th>Shoot days</th><th>Still to fill in</th><th /></tr>
            </thead>
            <tbody>
              {panel.talent.map((t) => (
                <tr key={t.hire_id}>
                  <td>
                    <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{t.name}</span>
                    {t.role && <span className="text-xs ml-1.5" style={{ color: "var(--text-secondary)" }}>{t.role}</span>}
                  </td>
                  <td>
                    {t.shoot_dates.length
                      ? <DateText>{t.shoot_dates.map((d) => (d ? displaySpan(d, d) : "No date")).join(", ")}</DateText>
                      : <span className="text-xs" style={{ color: "var(--text-muted)" }}>—</span>}
                  </td>
                  <td>
                    {t.gaps.length
                      ? <span className="text-xs" style={{ color: "var(--warning)" }}>{t.gaps.join(" · ")}</span>
                      : <span className="text-xs" style={{ color: "var(--success)" }}>Ready</span>}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy || dirty}
                      onClick={() => download(`${t.hire_id}/pdf`, t.hire_id, `Call sheet - ${t.name}.pdf`)}
                      aria-label={`Download ${t.name}'s call sheet`}>
                      {busy === t.hire_id ? "Preparing…" : "PDF"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {panel.held.length > 0 && panel.talent.length > 0 && (
        <p className="text-xs -mt-4 mb-6" style={{ color: "var(--text-muted)" }}>
          On hold, no sheet until confirmed: {panel.held.join(", ")}.
        </p>
      )}

      <section className="card p-5" aria-labelledby="says-heading">
        <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
          <div>
            <h2 id="says-heading" className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>What every sheet says</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>Set once for the job; it prints on every talent&apos;s sheet.</p>
          </div>
          {dirty && (
            <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={busy === "save"}>
              {busy === "save" ? "Saving…" : "Save"}
            </button>
          )}
        </div>

        <fieldset className="mb-5">
          <legend className="field-label">Who to call</legend>
          <p className="text-sm mb-2" style={{ color: "var(--text-primary)" }}>
            You, always first —{" "}
            {panel.producer_phone
              ? <DateText>{panel.producer_phone}</DateText>
              : <span style={{ color: "var(--warning)" }}>no number yet</span>}
            <span className="text-xs ml-2" style={{ color: "var(--text-secondary)" }}>
              <Link href={`/jobs/${id}/travel`} style={{ color: "var(--accent-text)" }}>Change on Travel</Link>
            </span>
          </p>
          <p className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>
            Tick the crew an agent may call. Only their name, role and phone print; nobody else&apos;s number goes out.
          </p>
          {panel.crew.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>No crew hired yet.</p>
          ) : (
            <div className="grid gap-1.5 md:grid-cols-2">
              {panel.crew.map((c) => (
                <label key={c.hire_id} className="flex items-center gap-2 text-sm" style={{ color: "var(--text-primary)" }}>
                  <input type="checkbox" checked={draft.contacts.includes(c.hire_id)} onChange={() => toggleContact(c.hire_id)}
                    aria-label={`${c.name}${c.role ? `, ${c.role}` : ""}: on every talent sheet`} />
                  {c.name}
                  {c.role && <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{c.role}</span>}
                  {!c.has_phone && <span className="text-xs" style={{ color: "var(--text-muted)" }}>no phone on file</span>}
                </label>
              ))}
            </div>
          )}
        </fieldset>

        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <label htmlFor="hotel-note" className="field-label">Hotel note</label>
            <textarea id="hotel-note" rows={4} maxLength={600} value={draft.hotel_note ?? ""} onChange={(e) => edit({ hotel_note: e.target.value })}
              placeholder="Room and tax billed to the production. Incidentals on your own card." className="field-input" />
          </div>
          <div>
            <label htmlFor="prep-note" className="field-label">Before you arrive</label>
            <textarea id="prep-note" rows={4} maxLength={600} value={draft.prep_note ?? ""} onChange={(e) => edit({ prep_note: e.target.value })}
              placeholder={"No makeup\nClean, dry hair\nNude base layers"} className="field-input" />
          </div>
          <div>
            <label htmlFor="other-note" className="field-label">Also</label>
            <textarea id="other-note" rows={4} maxLength={600} value={draft.notes ?? ""} onChange={(e) => edit({ notes: e.target.value })}
              placeholder="Breakfast and lunch on location." className="field-input" />
          </div>
        </div>
      </section>
    </div>
  );
}
