"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";

interface WrapReport {
  project_id: string;
  project_name: string;
  shoot_date: string | null;
  wrapped: boolean;
  html: string;
  share_url: string | null;
}

/**
 * The wrap report — a record of the day, rendered by the backend.
 *
 * The HTML is injected rather than rebuilt in React on purpose: it is the same
 * Jinja template that could later be emailed or printed, and having one renderer
 * is what keeps those from drifting. It is autoescaped at the insertion point,
 * and its CSS is scoped under .wrap-report so it can't repaint the app.
 */
export default function WrapReportPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<WrapReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api
      .get<WrapReport>(`/api/projects/${id}/wrap`)
      .then((r) => {
        setReport(r);
        setShareUrl(r.share_url);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load the wrap report"));
  }, [id]);

  async function share() {
    setBusy(true);
    try {
      const { url } = await api.post<{ url: string | null }>(`/api/projects/${id}/wrap/share`, {});
      setShareUrl(url);
      if (url) {
        // Best-effort: clipboard access is refused outside a secure context and
        // in some embedded browsers. The link is on screen either way, so a
        // refusal costs nothing but the convenience.
        try {
          await navigator.clipboard.writeText(url);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch { /* the URL is displayed; they can select it */ }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create a share link");
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    setBusy(true);
    try {
      await api.delete(`/api/projects/${id}/wrap/share`);
      setShareUrl(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't turn off the link");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="max-w-5xl mx-auto px-4 md:px-8 py-10"><LoadError message={error} /></div>;
  if (!report) {
    return (
      <div className="max-w-5xl mx-auto px-4 md:px-8 py-10 space-y-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-6 space-y-4">
      {/* Not a warning, just an honest label: the report renders for a job that
          hasn't happened yet, and half of it will be empty until it has. */}
      {!report.wrapped && (
        <p className="text-sm px-4 py-3 rounded-lg" style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)" }}>
          This shoot hasn&apos;t happened yet — the report will fill in as the day does.
        </p>
      )}

      {/* Sharing sits above the report, not buried under it — it is the reason
          a producer opens this page a second time. */}
      <div className="card px-5 py-4 space-y-3">
        {shareUrl ? (
          <>
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Anyone with this link can read this report
              </span>
              <div className="flex gap-2 shrink-0">
                <button onClick={share} disabled={busy} className="btn btn-ghost btn-sm">
                  {copied ? "Copied" : "Copy link"}
                </button>
                <button onClick={revoke} disabled={busy} className="btn btn-ghost btn-sm">
                  {busy ? "…" : "Turn off"}
                </button>
              </div>
            </div>
            <p className="text-xs font-mono break-all px-3 py-2 rounded"
               style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)" }}>
              {shareUrl}
            </p>
            {/* Says exactly what travels, because "share" on its own does not.
                No phone numbers or email addresses are in the report at all. */}
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              They&apos;ll see the schedule, the crew and talent names with their roles and call
              times, and the location addresses. No phone numbers or email addresses — those stay
              in your Roster. Turning the link off kills it immediately.
            </p>
          </>
        ) : (
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="min-w-0">
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Share this report</p>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                Creates a link anyone can open without an account. You can turn it off later.
              </p>
            </div>
            <button onClick={share} disabled={busy} className="btn btn-primary btn-sm shrink-0">
              {busy ? "Creating…" : "Create link"}
            </button>
          </div>
        )}
      </div>

      <div dangerouslySetInnerHTML={{ __html: report.html }} />

      <div className="flex justify-between items-center pt-2">
        <Link href={`/projects/${id}`} className="btn btn-ghost btn-sm">← Back to the project</Link>
        <button onClick={() => window.print()} className="btn btn-ghost btn-sm">Print</button>
      </div>
    </div>
  );
}
