"use client";

/* Job home: Pre-production · Shoot days · Wrap (docs/job-layer-plan.md §7).
 * Each tab fetches its own data, the same pattern every /projects/[id]/*
 * page uses — this layout only owns the header (name, date span) and the
 * tab strip.
 */

import { useEffect, useState } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import AppFooter from "@/components/AppFooter";
import { DateText } from "@/components/DateText";

interface Job {
  id: string;
  name: string;
  crew_dates: Record<string, [string, string][]>;
}
interface DaySummary { id: string; shoot_date: string | null }
interface JobHome { job: Job; days: DaySummary[] }

const TABS: { label: string; path: string }[] = [
  { label: "Pre-production", path: "/pre-production" },
  { label: "Job info", path: "/job-info" },
  { label: "Vendors", path: "/vendors" },
  { label: "Rooming", path: "/rooming" },
  { label: "Per diem", path: "/per-diem" },
  { label: "Travel", path: "/travel" },
  { label: "Talent sheets", path: "/talent-sheets" },
  { label: "Shoot days", path: "/shoot-days" },
  { label: "Wrap", path: "/wrap" },
  { label: "Budget", path: "/budget" },
  { label: "PC log", path: "/pc-log" },
];

function dateSpan(job: Job, days: DaySummary[]): string | null {
  const every = Object.values(job.crew_dates ?? {}).flat().flatMap((s) => s);
  const pool = every.length ? every : days.map((d) => d.shoot_date).filter((d): d is string => !!d);
  if (!pool.length) return null;
  const sorted = [...pool].sort();
  const first = sorted[0], last = sorted[sorted.length - 1];
  const fmt = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return first === last ? fmt(first) : `${fmt(first)} – ${fmt(last)}`;
}

export default function JobLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const [home, setHome] = useState<JobHome | null>(null);
  const [dark, setDark] = useState(true);

  useEffect(() => {
    setDark(document.documentElement.getAttribute("data-theme") !== "light");
  }, []);

  // Same toggle the dashboard and the day sidebar carry — every Jobs screen has
  // to be checked in both themes (docs/design-system.md), so it can't only be
  // reachable from somewhere else.
  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  useEffect(() => {
    const refresh = () => api.get<JobHome>(`/api/jobs/${id}`).then(setHome).catch(() => {});
    createClient().auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace("/auth/login"); return; }
      refresh();
    });
    // A tab that changes what the header shows (the crew dates set the span)
    // says so, rather than the header going stale until a reload.
    window.addEventListener("job:changed", refresh);
    return () => window.removeEventListener("job:changed", refresh);
  }, [id, router]);

  function isActive(path: string) {
    return pathname === `/jobs/${id}${path}`;
  }

  const span = home ? dateSpan(home.job, home.days) : null;

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="sticky top-0 z-10 px-6 py-3"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center justify-between mb-3">
          <Link href="/dashboard" className="text-xs" style={{ color: "var(--text-secondary)" }}>← All jobs</Link>
          <div className="flex items-center gap-4">
            <Link href="/holds" className="text-xs" style={{ color: "var(--text-secondary)" }}>Holds</Link>
            <Link href="/roster" className="text-xs" style={{ color: "var(--text-secondary)" }}>Master Roster</Link>
            <button onClick={toggleTheme} className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {dark ? "Light mode" : "Dark mode"}
            </button>
          </div>
        </div>
        <div className="flex items-baseline gap-3 flex-wrap mb-3">
          <h1 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            {home?.job.name ?? <span className="opacity-0">Loading</span>}
          </h1>
          {span && <DateText muted>{span}</DateText>}
        </div>
        {/* Nine tabs don't fit a phone: the strip scrolls sideways on its own
            rather than widening the whole page. */}
        <nav className="flex gap-1 overflow-x-auto -mx-6 px-6" style={{ scrollbarWidth: "none" }}>
          {TABS.map((t) => (
            <Link
              key={t.path}
              href={`/jobs/${id}${t.path}`}
              className={`nav-item${isActive(t.path) ? " active" : ""}`}
              style={{ display: "inline-flex", flexShrink: 0, whiteSpace: "nowrap" }}
            >
              {t.label}
            </Link>
          ))}
        </nav>
      </header>

      {/* 5xl, like the day pages: the Deal Memos table has five date columns. */}
      <main className="flex-1 w-full max-w-5xl mx-auto px-6 py-8">
        {children}
      </main>
      <AppFooter />
    </div>
  );
}
