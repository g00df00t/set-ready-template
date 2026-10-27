"use client";

// The Jobs version of the dashboard body (docs/job-layer-plan.md §7): name,
// date span, day count, "New job", and deleting a job. Rendered inside
// dashboard/page.tsx's own header/roster-card/footer chrome, which is shared
// with the current version — only this list swaps.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { CardListSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { DateText } from "@/components/DateText";
import { useToast } from "@/components/Toast";

interface JobSummary {
  id: string;
  name: string;
  day_count: number;
  first_date: string | null;
  last_date: string | null;
}

function fmt(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function JobsDashboardBody() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const { show: showToast, node: toastNode } = useToast();

  const load = useCallback(() => {
    setLoadError(false);
    api.get<JobSummary[]>("/api/jobs").then(setJobs).catch(() => setLoadError(true));
  }, []);

  useEffect(load, [load]);

  // Two steps, like removing a hire: the first click asks and names what
  // goes with the job, the second deletes.
  async function handleDelete(job: JobSummary) {
    if (confirmDelete !== job.id) { setConfirmDelete(job.id); return; }
    setDeleting(job.id);
    try {
      await api.delete(`/api/jobs/${job.id}`);
      setJobs((js) => js && js.filter((j) => j.id !== job.id));
      showToast(`${job.name} deleted`);
    } catch (err) {
      showToast(err instanceof Error ? `Couldn't delete: ${err.message}` : "Couldn't delete that job.");
    } finally {
      setDeleting(null);
      setConfirmDelete(null);
    }
  }

  return (
    <>
      {toastNode}
      {/* Both sides sit in by the cards' own px-5 (1.25rem): the heading lines up
          with the text in the Roster card and the list below, the button with the
          Roster card's button. */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)", paddingLeft: "1.25rem" }}>Jobs</h2>
        <Link href="/jobs/new" className="btn btn-primary" style={{ minWidth: "11rem", marginRight: "1.25rem" }}>
          New job
        </Link>
      </div>

      {jobs === null ? (
        <CardListSkeleton rows={3} />
      ) : loadError ? (
        <LoadError message="Couldn't load your jobs." onRetry={load} />
      ) : jobs.length === 0 ? (
        <div className="card p-8 text-center">
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>No jobs yet.</p>
          <Link href="/jobs/new" className="btn btn-primary">Create your first job</Link>
        </div>
      ) : (
        <ul className="space-y-2">
          {jobs.map((job) => (
            <li key={job.id}>
              {/* The link stretches over the whole card (its ::after), so the
                  card still opens the job anywhere you click it; the delete
                  controls sit above that layer. A button can't go inside the
                  link itself. */}
              <div className="card-raised relative flex items-center justify-between gap-4 px-5 py-4">
                <div>
                  <Link href={`/jobs/${job.id}`} className="text-sm font-medium after:absolute after:inset-0 after:content-['']"
                    style={{ color: "var(--text-primary)" }}>
                    {job.name}
                  </Link>
                  <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                    {job.first_date ? (
                      <DateText>{job.first_date === job.last_date ? fmt(job.first_date) : `${fmt(job.first_date)} – ${fmt(job.last_date!)}`}</DateText>
                    ) : "No dates set"}
                  </p>
                </div>
                <div className="relative z-[1] flex items-center gap-3">
                  {confirmDelete === job.id ? (
                    <span className="flex flex-wrap items-center justify-end gap-1.5">
                      <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        Its {job.day_count === 1 ? "day" : `${job.day_count} days`}, hires and call sheets go too.
                      </span>
                      <span className="flex gap-1.5">
                        <button onClick={() => handleDelete(job)} disabled={deleting === job.id} className="btn btn-sm btn-confirm-remove">
                          {deleting === job.id ? "Deleting…" : "Delete job"}
                        </button>
                        <button onClick={() => setConfirmDelete(null)} className="btn btn-ghost btn-sm">Cancel</button>
                      </span>
                    </span>
                  ) : (
                    <>
                      <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        <DateText>{job.day_count}</DateText> {job.day_count === 1 ? "day" : "days"}
                      </span>
                      <button onClick={() => handleDelete(job)} className="btn btn-remove" aria-label={`Delete ${job.name}`}>
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
