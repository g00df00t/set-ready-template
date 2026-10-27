"use client";

/* Holds — every upcoming job on one page, like the producer's Crew Holds sheet
 * (docs/producer-documents-map.md §1.1): each job stacked, its roles and people
 * down the side, its dates across, 1 / 2 / ✓ in the cells. Anyone on two
 * jobs on the same date is flagged at the top.
 *
 * Read-only: holds are set where the people are, on each job's
 * Pre-production tab (status menu, Roles checklist). The API works it all out
 * (backend services/holds.py).
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";
import AppFooter from "@/components/AppFooter";
import { TableSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateText } from "@/components/DateText";
import { addDays, displaySpan } from "@/lib/jobDates";

interface Row { kind: "hire" | "slot"; hire_id: string | null; slot_id: string | null; role: string; name: string | null; status: string; label: string; cells: Record<string, string> }
interface Block { job: { id: string; name: string; client_name: string | null }; dates: string[]; rows: Row[]; open_roles: number; holds: number }
interface Holds { jobs: Block[]; conflicts: { name: string; dates: string[]; jobs: { job: string; label: string }[] }[] }

// Consecutive dates as spans, for "Oct 11 → 17".
function spansOf(dates: string[]): [string, string][] {
  const out: [string, string][] = [];
  for (const d of dates) {
    const last = out[out.length - 1];
    if (last && addDays(last[1], 1) === d) last[1] = d; else out.push([d, d]);
  }
  return out;
}

export default function HoldsPage() {
  const router = useRouter();
  const [data, setData] = useState<Holds | null>(null);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(() => {
    setLoadError(false);
    api.get<Holds>("/api/holds").then(setData).catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    createClient().auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace("/auth/login"); return; }
      load();
    });
  }, [router, load]);

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="sticky top-0 z-10 px-6 py-3 flex items-center justify-between"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <Link href="/dashboard" className="text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)", textDecoration: "none" }}>
          SET&gt;READY
        </Link>
        <Link href="/dashboard" className="text-xs" style={{ color: "var(--text-secondary)" }}>← All jobs</Link>
      </header>

      <main className="flex-1 w-full max-w-6xl mx-auto px-6 py-8">
        <h1 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Holds</h1>
        <p className="text-sm mt-1 mb-6" style={{ color: "var(--text-secondary)" }}>
          Every upcoming job: 1 and 2 are first and second holds, ✓ is confirmed. Set them on each job&apos;s Pre-production tab.
        </p>

        {loadError && <LoadError message="Couldn't load your holds." onRetry={load} />}
        {!data && !loadError && <TableSkeleton />}

        {data && data.conflicts.length > 0 && (
          <div className="card p-4 mb-6" role="status" style={{ borderColor: "var(--warning)" }}>
            <p className="text-sm font-medium mb-1" style={{ color: "var(--text-primary)" }}>Held on two jobs at once</p>
            <ul className="text-sm grid gap-0.5" style={{ color: "var(--text-secondary)" }}>
              {data.conflicts.map((c) => (
                <li key={`${c.name}-${c.dates[0]}-${c.jobs.map((j) => j.job).join()}`}>
                  <span style={{ color: "var(--text-primary)" }}>{c.name}</span>: {c.jobs.map((j) => `${j.job} (${j.label})`).join(" and ")}
                  {" · "}<DateText>{spansOf(c.dates).map(([a, b]) => displaySpan(a, b)).join(", ")}</DateText>
                </li>
              ))}
            </ul>
          </div>
        )}

        {data && data.jobs.length === 0 && (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>No upcoming jobs.</p>
        )}

        {data?.jobs.map((b) => (
          <section key={b.job.id} className="mb-8" aria-labelledby={`job-${b.job.id}`}>
            <div className="flex items-baseline justify-between gap-3 flex-wrap mb-2">
              <h2 id={`job-${b.job.id}`} className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>
                <Link href={`/jobs/${b.job.id}/pre-production`} style={{ color: "inherit" }}>{b.job.name}</Link>
                {b.job.client_name && <span className="text-sm font-normal ml-2" style={{ color: "var(--text-secondary)" }}>{b.job.client_name}</span>}
              </h2>
              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {b.holds} on hold · {b.open_roles} {b.open_roles === 1 ? "role" : "roles"} not cast
              </span>
            </div>
            <div className="data-table-raised">
              <table>
                <thead>
                  <tr>
                    <th>Role</th>
                    <th>Name</th>
                    {b.dates.map((d) => <th key={d} style={{ textAlign: "center" }}><DateText>{displaySpan(d, d)}</DateText></th>)}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.length === 0 && (
                    <tr><td colSpan={b.dates.length + 2} className="text-sm" style={{ color: "var(--text-muted)" }}>
                      Nobody held yet, and no roles listed.
                    </td></tr>
                  )}
                  {b.rows.map((r) => (
                    <tr key={r.hire_id ?? r.slot_id ?? r.role}>
                      <td className="text-sm" style={{ color: "var(--text-primary)" }}>{r.role || "—"}</td>
                      <td className="text-sm" style={{ color: r.name ? "var(--text-primary)" : "var(--text-muted)" }}>
                        {r.name ?? "Not cast"}
                        {r.kind === "hire" && r.status !== "confirmed" && (
                          <span className="text-xs ml-1.5" style={{ color: "var(--accent-text)" }}>{r.label}</span>
                        )}
                      </td>
                      {b.dates.map((d) => {
                        const v = r.cells[d];
                        return (
                          <td key={d} style={{ textAlign: "center" }}>
                            {v ? <DateText><span style={{ color: v === "✓" ? "var(--success)" : "var(--accent-text)", fontWeight: 600 }}
                              aria-label={v === "✓" ? "confirmed" : `${v === "1" ? "1st" : "2nd"} hold`}>{v}</span></DateText>
                              : <span style={{ color: "var(--text-muted)" }}>·</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </main>
      <AppFooter />
    </div>
  );
}
