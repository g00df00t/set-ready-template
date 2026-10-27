"use client";

import { useEffect, useState } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase";
import AppFooter from "@/components/AppFooter";
import { StepNav } from "@/components/StepNav";
import { hasWrapped } from "@/lib/nextShoot";
import { useBrand } from "@/components/BrandTheme";
import { useBeta } from "@/lib/useBeta";
import { LABELS, offDatesLabel, planDays, type DatesByType } from "@/lib/jobDates";

interface Project {
  id: string;
  name: string;
  shoot_date: string | null;
  job_id: string | null;
}

interface JobBreadcrumb {
  name: string;
  /** "Day 2 of 4", or what the day is when it isn't a numbered shoot day. */
  where: string;
}

interface Summary {
  crew_count: number;
  talent_count: number;
  contact_count: number;
  schedule_item_count: number;
  has_location: boolean;
  has_accommodation: boolean;
  call_sheet_generated: boolean;
  call_sheet_sent: boolean;
}

const NAV: { label: string; path: string; countKey?: string }[] = [
  { label: "Production Overview", path: "" },
  { label: "Crew",                path: "/crew",     countKey: "crew_count" },
  { label: "Talent",              path: "/talent",   countKey: "talent_count" },
  { label: "Agency & Client",     path: "/contacts", countKey: "contact_count" },
  { label: "Location",            path: "/location" },
  // Meals then Accommodations, matching the sheet: meal plan is section 8
  // there and accommodations section 10. The sidebar had them the other way
  // round until 2026-09-09 — keep both in step with call_sheet.html.j2.
  { label: "Meal Plan",           path: "/meals" },
  { label: "Accommodations",      path: "/accommodations" },
  { label: "Schedule",            path: "/schedule", countKey: "schedule_item_count" },
  { label: "Deal Memos",          path: "/deal-memos" },
  { label: "Notes",               path: "/notes" },
];

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const { betaJobs } = useBeta();
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [jobBreadcrumb, setJobBreadcrumb] = useState<JobBreadcrumb | null>(null);
  const [dark, setDark] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const brand = useBrand();

  useEffect(() => {
    setDark(document.documentElement.getAttribute("data-theme") !== "light");
    api.get<Project>(`/api/projects/${id}`).then(setProject).catch(() => {});
    api.get<Summary>(`/api/projects/${id}/summary`).then(setSummary).catch(() => {});
  }, [id]);

  // The breadcrumb ("← Northwind Athletic · Day 2 of 3") is Jobs-only — the
  // day workspace itself is otherwise unchanged (plan §7). Only fetched once
  // both the account's flag and this day's own job_id are known, so a
  // non-beta account never makes this call at all.
  useEffect(() => {
    if (!betaJobs || !project?.job_id) { setJobBreadcrumb(null); return; }
    api.get<{ job: { name: string; crew_dates: DatesByType }; days: { id: string; shoot_date: string | null }[] }>(`/api/jobs/${project.job_id}`)
      .then(({ job, days }) => {
        // Same numbering as the Shoot days tab (placeholders count), so "Day
        // 2" can't mean one thing there and another here.
        const plan = planDays(days, job.crew_dates ?? {});
        const me = plan.find((e) => e.day?.id === id);
        const count = plan.filter((e) => e.number).length;
        const where = me?.number ? `Day ${me.number} of ${count}`
          : me?.dayType ? LABELS[me.dayType]
            : me?.outside ? offDatesLabel(me.where) : "No date yet";
        setJobBreadcrumb({ name: job.name, where });
      })
      .catch(() => {});
  }, [betaJobs, project?.job_id, id]);

  // Close drawer on route change
  useEffect(() => { setDrawerOpen(false); }, [pathname]);

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/auth/login?signedout=1");
  }

  function isActive(path: string) {
    const full = `/projects/${id}${path}`;
    return path === "" ? pathname === full : pathname.startsWith(full);
  }

  const sidebarContent = (
    <>
      {/* Wordmark */}
      <div className="px-4 pt-5 pb-3 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
        {/* Product first, company underneath as the qualifier — the ordering
            Wispy uses, and the honest one for software someone is using rather
            than software they made. An earlier version had it the other way
            round. */}
        <Link href="/dashboard" className="block min-w-0" onClick={() => setDrawerOpen(false)}>
          <span className="block text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>
            SET&gt;READY
          </span>
          {brand.name && (
            <span className="block truncate mt-0.5" style={{
              fontSize: "9.5px", fontWeight: 600, letterSpacing: "0.16em",
              textTransform: "uppercase", color: "var(--text-muted)",
            }}>
              {brand.name}
            </span>
          )}
        </Link>
        {/* Close button — mobile only */}
        <button
          className="md:hidden text-lg leading-none"
          onClick={() => setDrawerOpen(false)}
          style={{ color: "var(--text-muted)" }}
        >
          ✕
        </button>
      </div>

      {/* Project info — a job breadcrumb in place of the plain project name
          once both the account's on Jobs and this day belongs to one. */}
      <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
        {jobBreadcrumb ? (
          <>
            <Link
              // Back one level — to the job's Shoot days, where this day sits —
              // not the job's front door, which opens on Pre-production.
              href={`/jobs/${project!.job_id}/shoot-days`}
              className="text-xs font-semibold leading-snug truncate block"
              style={{ color: "var(--text-secondary)" }}
              onClick={() => setDrawerOpen(false)}
            >
              ← {jobBreadcrumb.name}
            </Link>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              {jobBreadcrumb.where}
            </p>
          </>
        ) : project ? (
          <>
            <p className="text-xs font-semibold leading-snug truncate" style={{ color: "var(--text-primary)" }}>
              {project.name}
            </p>
            {project.shoot_date ? (
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                {new Date(project.shoot_date + "T00:00:00").toLocaleDateString("en-US", {
                  weekday: "short", month: "short", day: "numeric",
                })}
              </p>
            ) : (
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>No shoot date</p>
            )}
          </>
        ) : (
          <div className="h-3 w-28 rounded" style={{ background: "var(--bg-elevated)" }} />
        )}
      </div>

      {/* Nav items — Deal Memos moves onto the job's Pre-production tab once
          this day belongs to one (plan §7), so it drops out of this list. */}
      <nav className="px-2 py-3 space-y-0.5">
        {NAV.filter((n) => !(jobBreadcrumb && n.path === "/deal-memos")).map(({ label, path, countKey }) => {
          const active = isActive(path);
          const count = countKey && summary ? (summary as unknown as Record<string, number>)[countKey] : null;
          return (
            <Link
              key={path}
              href={`/projects/${id}${path}`}
              className={`nav-item${active ? " active" : ""}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span>{label}</span>
            </Link>
          );
        })}
        {/* Only once the day is behind them. Before that the report is mostly
            empty, and a nav item for it would read as a step they've skipped. */}
        {project && hasWrapped(project) && (
          <Link
            href={`/projects/${id}/wrap`}
            className={`nav-item${isActive("/wrap") ? " active" : ""}`}
            onClick={() => setDrawerOpen(false)}
          >
            <span>Wrap Report</span>
          </Link>
        )}

        {/* Last on purpose, and styled apart from everything above it — every
            other page here is an input that feeds the call sheet, so it's the
            main action in this sidebar, not one item among equals. */}
        <Link
          href={`/projects/${id}/call-sheet`}
          className={`nav-item-primary mt-2${isActive("/call-sheet") ? " active" : ""}`}
          onClick={() => setDrawerOpen(false)}
        >
          Call Sheet
        </Link>
      </nav>

      {/* Footer */}
      <div className="px-2 py-3 mt-8 space-y-0.5" style={{ borderTop: "1px solid var(--border)" }}>
        <Link href="/roster" className="nav-item" onClick={() => setDrawerOpen(false)}>Master Roster</Link>
        <Link href="/dashboard" className="nav-item" onClick={() => setDrawerOpen(false)}>← {jobBreadcrumb ? "All Jobs" : "All Projects"}</Link>
        <div className="flex items-center justify-between px-3 pt-2">
          <button onClick={toggleTheme} className="text-xs" style={{ color: "var(--text-muted)" }}>
            {dark ? "Light mode" : "Dark mode"}
          </button>
          <button onClick={handleSignOut} className="text-xs" style={{ color: "var(--text-muted)" }}>
            Sign out
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen" style={{ background: "var(--bg-base)" }}>

      {/* ── Mobile top bar ── */}
      <div
        className="md:hidden fixed top-0 left-0 right-0 z-40 flex items-center justify-between px-4"
        style={{ height: "48px", background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <Link href="/dashboard">
          <span className="text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>SET&gt;READY</span>
        </Link>
        <div className="flex items-center gap-3">
          {project && (
            <span className="text-xs truncate max-w-32" style={{ color: "var(--text-muted)" }}>{project.name}</span>
          )}
          <button
            onClick={() => setDrawerOpen(true)}
            className="flex flex-col gap-1 p-1"
            style={{ color: "var(--text-secondary)" }}
            aria-label="Open menu"
          >
            <span className="block w-5 h-px" style={{ background: "currentColor" }} />
            <span className="block w-5 h-px" style={{ background: "currentColor" }} />
            <span className="block w-5 h-px" style={{ background: "currentColor" }} />
          </button>
        </div>
      </div>

      {/* ── Mobile backdrop ── */}
      {drawerOpen && (
        <div
          className="md:hidden fixed inset-0 z-40"
          style={{ background: "var(--scrim)" }}
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* ── Sidebar (desktop: sticky, mobile: slide-in drawer) ── */}
      <aside
        className={`project-chrome flex flex-col w-52 shrink-0 h-screen overflow-y-auto fixed md:sticky top-0 z-50 md:z-auto transition-transform duration-200 ease-in-out ${drawerOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
        style={{ borderRight: "1px solid var(--border)" }}
      >
        {sidebarContent}
      </aside>

      {/* ── Page content ── */}
      <div className="flex flex-col flex-1 min-w-0 pt-12 md:pt-0">
        {/* Content and the step nav flow together, so the nav sits
            directly under whatever the page ends with. The spacer below takes
            the leftover height instead — putting flex-1 on the content wrapper
            stretched short pages and stranded the nav at the bottom of the
            viewport, far from the thing it follows. */}
        <div>{children}</div>
        <StepNav projectId={id} path={pathname.replace(`/projects/${id}`, "")} />
        <div className="flex-1" />
        <AppFooter />
      </div>
    </div>
  );
}
