"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import AppFooter from "@/components/AppFooter";
import { LoadError } from "@/components/LoadError";
import { useBeta } from "@/lib/useBeta";
import { JobsDashboardBody } from "@/components/JobsDashboardBody";

interface Project {
  id: string;
  name: string;
  shoot_date: string | null;
  created_at: string;
}

interface RosterEntrySlim {
  id: string;
}

export default function DashboardPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  // Only the screens are flagged — the account underneath is the same one
  // either way, which is why this single route just swaps its body instead
  // of being two pages (docs/job-layer-plan.md §11).
  const { betaJobs } = useBeta();
  const [loading, setLoading] = useState(true);
  const [dark, setDark] = useState(true);
  const [duplicating, setDuplicating] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  // Counts only, not the full entries — the dashboard card just needs "how
  // many", and null (rather than 0) while loading keeps it from flashing
  // "Nothing saved yet" before the real number arrives.
  const [rosterCounts, setRosterCounts] = useState<{ crew: number; talent: number; client: number } | null>(null);

  useEffect(() => {
    setDark(document.documentElement.getAttribute("data-theme") !== "light");
  }, []);

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  const loadProjects = useCallback(() => {
    setLoading(true); setLoadError(false);
    api.get<Project[]>("/api/projects")
      .then(setProjects)
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  }, []);

  // Separate from loadProjects and never blocks it — the card degrades to
  // showing nothing rather than holding up the page a visitor is actually
  // here for if this fails.
  const loadRosterCounts = useCallback(() => {
    Promise.all([
      api.get<RosterEntrySlim[]>("/api/roster?type=crew"),
      api.get<RosterEntrySlim[]>("/api/roster?type=talent"),
      api.get<RosterEntrySlim[]>("/api/roster?type=client"),
    ]).then(([crew, talent, client]) => {
      setRosterCounts({ crew: crew.length, talent: talent.length, client: client.length });
    }).catch((err) => console.error("Roster counts failed to load:", err));
  }, []);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace("/auth/login"); return; }
      loadProjects();
      loadRosterCounts();
    });
  }, [router, loadProjects, loadRosterCounts]);

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/auth/login?signedout=1");
  }

  async function handleDelete(e: React.MouseEvent, projectId: string) {
    e.preventDefault();
    if (confirmDelete !== projectId) { setConfirmDelete(projectId); return; }
    setDeleting(projectId);
    try {
      await api.delete(`/api/projects/${projectId}`);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch (err) {
      console.error(err);
    } finally {
      setDeleting(null);
      setConfirmDelete(null);
    }
  }

  async function handleDuplicate(e: React.MouseEvent, projectId: string) {
    e.preventDefault();
    setDuplicating(projectId);
    try {
      const copy = await api.post<Project>(`/api/projects/${projectId}/duplicate`, {});
      setProjects((prev) => [copy, ...prev]);
      router.push(`/projects/${copy.id}`);
    } catch (err) {
      console.error(err);
    } finally {
      setDuplicating(null);
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      {/* Header */}
      <header
        className="sticky top-0 z-10 px-6 py-3 flex items-center justify-between"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>
          SET&gt;READY
        </span>
        <div className="flex items-center gap-4">
          {/* The one link here that isn't a utility toggle — Account and Sign
              out manage this page, Master Roster is the destination everything
              else is built on, so it gets button weight instead of blending in. */}
          {betaJobs && (
            // Every upcoming job's holds on one page, like the producer's Crew Holds sheet.
            <Link href="/holds" className="text-xs" style={{ color: "var(--text-secondary)" }}>Holds</Link>
          )}
          <Link href="/roster" className="btn btn-secondary btn-sm">
            Master Roster
          </Link>
          <button onClick={toggleTheme} className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {dark ? "Light mode" : "Dark mode"}
          </button>
          <Link href="/account" className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Account
          </Link>
          <button onClick={handleSignOut} className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Sign out
          </button>
        </div>
      </header>

      <main className="flex-1 w-full max-w-2xl mx-auto px-6 py-10">
        {/* Ahead of Projects on purpose — everything below reads from this,
            so it gets first billing rather than living in the header where
            it used to be easy to never notice. */}
        {rosterCounts && (
          <Link
            href="/roster"
            className="flex items-center justify-between gap-4 px-5 py-4 rounded-xl mb-6"
            style={{
              background: "linear-gradient(135deg, var(--accent-subtle), transparent 70%), var(--bg-surface)",
              border: "1px solid var(--border)",
            }}
          >
            <div>
              <p className="text-sm font-semibold mb-0.5" style={{ color: "var(--text-primary)" }}>Your Master Roster</p>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                {rosterCounts.crew + rosterCounts.talent + rosterCounts.client === 0 ? (
                  "Nothing saved yet"
                ) : (
                  <>
                    <span className="font-semibold tabular-nums" style={{ color: "var(--text-primary)" }}>{rosterCounts.crew}</span> crew
                    {" · "}
                    <span className="font-semibold tabular-nums" style={{ color: "var(--text-primary)" }}>{rosterCounts.talent}</span> talent
                    {" · "}
                    <span className="font-semibold tabular-nums" style={{ color: "var(--text-primary)" }}>{rosterCounts.client}</span> clients saved
                  </>
                )}
              </p>
            </div>
            <span className="btn btn-primary shrink-0" style={{ minWidth: "11rem" }}>Open Master Roster &rarr;</span>
          </Link>
        )}

        {betaJobs ? <JobsDashboardBody /> : (
        <>
        {/* Both sides sit in by the cards' own px-5 (1.25rem): the heading lines up
            with the text in the Roster card and the list below, the button with the
            Roster card's button. */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)", paddingLeft: "1.25rem" }}>Projects</h2>
          <Link href="/projects/new" className="btn btn-primary" style={{ minWidth: "11rem", marginRight: "1.25rem" }}>
            New project
          </Link>
        </div>

        {loading ? (
          <ul className="space-y-2">
            {[0,1,2].map((i) => (
              <li key={i} className="card px-5 py-4 space-y-2">
                <Skeleton width="45%" height="1rem" />
                <Skeleton width="28%" height="0.75rem" />
              </li>
            ))}
          </ul>
        ) : loadError ? (
          <LoadError message="Couldn't load your projects." onRetry={loadProjects} />
        ) : projects.length === 0 ? (
          <div className="py-10">
            <div className="card max-w-md mx-auto p-10">
              <p className="text-xs font-bold tracking-widest mb-5" style={{ color: "var(--accent)" }}>SET&gt;READY</p>
              <h3 className="text-2xl font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
                Your first call sheet is minutes away.
              </h3>
              <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>
                Build your crew list, set location and schedule, and send a professional call sheet to everyone on set.
              </p>

              <div className="flex gap-5 mb-8">
                {[
                  { n: "1", label: "Create a project", sub: "Name and shoot date" },
                  { n: "2", label: "Add crew & location", sub: "Paste from spreadsheet" },
                  { n: "3", label: "Generate & send", sub: "Call sheet built in seconds" },
                ].map((step) => (
                  <div key={step.n} className="flex-1">
                    <div
                      className="w-7 h-7 rounded-full flex items-center justify-center mb-2 text-xs font-bold"
                      style={{ background: "var(--accent)", color: "#fff" }}
                    >
                      {step.n}
                    </div>
                    <p className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>{step.label}</p>
                    <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{step.sub}</p>
                  </div>
                ))}
              </div>

              <Link href="/projects/new" className="btn btn-primary" style={{ display: "block", textAlign: "center" }}>
                Create your first project
              </Link>
            </div>
          </div>
        ) : (
          <ul className="space-y-2">
            {projects.map((project) => (
              <li
                key={project.id}
                className="card flex items-center hover:border-[var(--accent)] transition-colors"
                style={{ borderColor: "var(--border)" }}
                onMouseLeave={() => setConfirmDelete(null)}
              >
                <Link href={`/projects/${project.id}`} className="flex-1 px-5 py-4">
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    {project.name}
                  </p>
                  {project.shoot_date ? (
                    <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                      {new Date(project.shoot_date + "T00:00:00").toLocaleDateString("en-US", {
                        weekday: "short", month: "short", day: "numeric", year: "numeric",
                      })}
                    </p>
                  ) : (
                    <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>No shoot date</p>
                  )}
                </Link>
                <div className="flex items-center gap-2 mr-3">
                  <button
                    onClick={(e) => handleDuplicate(e, project.id)}
                    disabled={duplicating === project.id}
                    className="btn btn-ghost btn-sm"
                  >
                    {duplicating === project.id ? "Copying…" : "Duplicate"}
                  </button>
                  <button
                    onClick={(e) => handleDelete(e, project.id)}
                    disabled={deleting === project.id}
                    className="btn btn-sm"
                    style={{
                      color: confirmDelete === project.id ? "var(--danger)" : "var(--text-muted)",
                      background: "transparent",
                      border: confirmDelete === project.id ? "1px solid var(--danger)" : "1px solid transparent",
                    }}
                  >
                    {deleting === project.id ? "Deleting…" : confirmDelete === project.id ? "Sure?" : "Delete"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        </>
        )}
      </main>
      <AppFooter />
    </div>
  );
}
