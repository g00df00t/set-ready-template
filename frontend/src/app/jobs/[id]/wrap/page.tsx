"use client";

// Links to each day's wrap report. Reconciliation arrives here in Phase 3
// (docs/job-layer-plan.md §7).

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { CardListSkeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";
import { hasWrapped } from "@/lib/nextShoot";
import { DateText } from "@/components/DateText";

interface DaySummary { id: string; name: string; shoot_date: string | null }

function fmtDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

export default function JobWrapPage() {
  const { id } = useParams<{ id: string }>();
  const [days, setDays] = useState<DaySummary[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(() => {
    setLoadError(false);
    api.get<{ days: DaySummary[] }>(`/api/jobs/${id}`)
      .then((r) => setDays(r.days))
      .catch(() => setLoadError(true));
  }, [id]);

  useEffect(load, [load]);

  const wrapped = days?.filter((d) => hasWrapped(d)) ?? [];

  return (
    <div>
      <h2 className="text-lg font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Wrap</h2>
      <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
        A wrap report for each day that&apos;s happened. Rendered live — confirmations keep arriving after a day
        ends, so nothing here is a stored snapshot.
      </p>

      {days === null ? (
        <CardListSkeleton rows={2} />
      ) : loadError ? (
        <LoadError message="Couldn't load this job's days." onRetry={load} />
      ) : wrapped.length === 0 ? (
        <div className="card p-8 text-center">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            No days have finished yet. A wrap report appears here the day after each shoot day.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {wrapped.map((day) => (
            <li key={day.id}>
              <Link href={`/projects/${day.id}/wrap`} className="card-raised flex items-center justify-between px-5 py-4">
                <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{day.name}</span>
                {day.shoot_date && (
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}><DateText>{fmtDate(day.shoot_date)}</DateText></span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
