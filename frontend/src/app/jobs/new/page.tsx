"use client";

// "New job" — what "New project" becomes for a Jobs-beta account. Creates the
// job and its Day 1 in one call (POST /api/jobs), and lands on the job's
// Pre-production tab.
//
// The shoot is picked as a span, with the same calendar the Crew & dates table
// uses. Day 1 is created on its first day, and the whole span becomes the
// crew's shoot dates — so the Pre-production page opens past "set the crew's
// shoot dates" instead of asking for them a second time.

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Popover } from "@/components/Popover";
import { RangeCalendar } from "@/components/RangeCalendar";
import { DateText } from "@/components/DateText";
import { displaySpan, spanDays, toIso, type Span } from "@/lib/jobDates";

export default function NewJobPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [shoot, setShoot] = useState<Span | null>(null);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const fieldRef = useRef<HTMLDivElement | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const { job } = await api.post<{ job: { id: string } }>("/api/jobs", {
        name,
        shoot_date: shoot?.[0] ?? null,
      });
      if (shoot) {
        // Best-effort: the job exists either way, and the Pre-production page
        // simply asks for the shoot dates if this didn't land.
        await api.put(`/api/jobs/${job.id}/crew-dates`, { crew_dates: { shoot: [shoot] } }).catch(() => {});
      }
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="px-6 py-3"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <Link href="/dashboard" className="text-xs" style={{ color: "var(--text-secondary)" }}>
          ← Dashboard
        </Link>
      </header>

      <main className="flex-1 w-full max-w-md mx-auto px-6 py-12">
        <h2 className="text-xl font-semibold mb-8" style={{ color: "var(--text-primary)" }}>
          New job
        </h2>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="field-label" htmlFor="job-name">Job name</label>
              <input
                id="job-name"
                type="text"
                required
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Northwind Athletic — Fall 2026"
                className="field-input"
              />
            </div>

            <div ref={fieldRef} style={{ position: "relative" }}>
              <label className="field-label" htmlFor="job-shoot">Shoot dates (optional)</label>
              <button
                ref={triggerRef}
                id="job-shoot"
                type="button"
                onClick={() => setPicking((p) => !p)}
                className="field-input text-left"
                style={picking ? { borderColor: "var(--accent)", boxShadow: "0 0 0 3px var(--accent-subtle)" } : undefined}
                aria-haspopup="dialog"
                aria-expanded={picking}
              >
                {shoot ? (
                  <span className="flex items-baseline gap-2">
                    <DateText>{displaySpan(shoot[0], shoot[1])}</DateText>
                    {spanDays(shoot[0], shoot[1]) > 1 && <DateText muted>{spanDays(shoot[0], shoot[1])} days</DateText>}
                  </span>
                ) : (
                  <span style={{ color: "var(--text-muted)" }}>Pick the first and last shoot day</span>
                )}
              </button>
              <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
                Day 1 is created on the first day. Travel, prep and wrap can be added on the job.
              </p>

              {picking && (
                <Popover
                  anchorRef={triggerRef}
                  containerRef={fieldRef}
                  onClose={() => setPicking(false)}
                  ariaLabel="Shoot dates"
                  width={304}
                >
                  <RangeCalendar
                    dayType="shoot"
                    getBlocks={(t) => (t === "shoot" && shoot ? [shoot] : [])}
                    initialMonth={(shoot?.[0] ?? toIso(new Date())).slice(0, 7)}
                    range
                    allowSeparate={false}
                    who="New job"
                    isCrewRow
                    onCommit={(a, b) => { setShoot([a, b]); setPicking(false); }}
                    onRemove={() => setShoot(null)}
                  />
                </Popover>
              )}
            </div>

            {error && <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

            <button type="submit" disabled={loading} className="btn btn-primary w-full">
              {loading ? "Creating…" : "Create job"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
