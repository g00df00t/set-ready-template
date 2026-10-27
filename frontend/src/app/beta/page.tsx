"use client";

/* set-ready-set.com/beta — explains the Jobs version and turns it on.
 *
 * docs/job-layer-plan.md §11: per-person, not per-account (a team member can
 * be on either version), and reversible any time from /account. Turning it on
 * repairs this account's data first (the backfill, scoped to it) and converts
 * its old free-text deal memo dates once — see routers/account.py's set_beta.
 * Unlinked, like /master: reached only by typing the URL or the link Patrick
 * sends in the feature-showcase deck.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { useBeta } from "@/lib/useBeta";

export default function BetaPage() {
  const router = useRouter();
  const { betaJobs, setEnabled } = useBeta();
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [unparsed, setUnparsed] = useState<{ name: string; line: string }[] | null>(null);

  useEffect(() => {
    createClient().auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace("/auth/login"); return; }
      setSignedIn(true);
    });
  }, [router]);

  async function tryIt() {
    setWorking(true); setError("");
    try {
      const report = await setEnabled(true);
      if (report?.dates?.unparsed.length) {
        setUnparsed(report.dates.unparsed.map((u) => ({ name: u.name, line: u.line })));
      } else {
        router.push("/dashboard");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't switch you over. Nothing changed — try again.");
    } finally {
      setWorking(false);
    }
  }

  if (signedIn === null) return null;

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="px-6 py-3"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <Link href="/dashboard" className="text-xs" style={{ color: "var(--text-secondary)" }}>← Dashboard</Link>
      </header>

      <main className="flex-1 w-full max-w-xl mx-auto px-6 py-12">
        <p className="text-xs font-bold tracking-widest mb-4" style={{ color: "var(--accent)" }}>NEW</p>
        <h1 className="text-2xl font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
          Jobs: one place for the whole shoot
        </h1>
        <p className="text-sm mb-6 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          Today, a multi-day shoot is several separate projects with no shared home.
          Jobs adds that home: your crew&apos;s travel, prep, shoot and wrap dates set once
          for everyone, deal memos filled in from those dates, and every day of the job
          in one place. A one-day shoot becomes a job with one day &mdash; nothing else changes.
        </p>

        <div className="card p-5 mb-6 space-y-2.5">
          <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>What&apos;s different</p>
          <ul className="text-sm space-y-1.5" style={{ color: "var(--text-secondary)" }}>
            <li>&bull; The dashboard lists jobs, not individual days</li>
            <li>&bull; A job has a Pre-production tab (crew &amp; dates, deal memos), Shoot days, and Wrap</li>
            <li>&bull; Each day keeps its own call times, schedule, and crew list, unchanged</li>
            <li>&bull; Deal Memos moves from the day sidebar onto the job</li>
          </ul>
        </div>

        <div className="card p-5 mb-6">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Your existing projects come with you &mdash; nothing is lost, and{" "}
            <strong style={{ color: "var(--text-primary)" }}>Switch back</strong> in Account
            returns you to the current version at any time, reading the same data.
          </p>
        </div>

        {unparsed ? (
          <div className="card p-5 mb-6" style={{ borderColor: "var(--danger)" }}>
            <p className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
              You&apos;re switched on. A few old deal-memo date lines couldn&apos;t be read automatically:
            </p>
            <ul className="text-xs space-y-1 mb-3" style={{ color: "var(--text-secondary)" }}>
              {unparsed.map((u, i) => (
                <li key={i}><strong style={{ color: "var(--text-primary)" }}>{u.name}:</strong> &ldquo;{u.line}&rdquo;</li>
              ))}
            </ul>
            <p className="text-xs mb-4" style={{ color: "var(--text-secondary)" }}>
              Everything else came across. Re-enter these on the job&apos;s Pre-production tab.
            </p>
            <Link href="/dashboard" className="btn btn-primary">Go to your jobs</Link>
          </div>
        ) : betaJobs ? (
          <div className="card p-5 mb-6">
            <p className="text-sm" style={{ color: "var(--text-primary)" }}>You&apos;re already on the Jobs version.</p>
            <Link href="/dashboard" className="btn btn-primary mt-4" style={{ display: "inline-block" }}>Go to your jobs</Link>
          </div>
        ) : (
          <>
            <button onClick={tryIt} disabled={working} className="btn btn-primary w-full">
              {working ? "Switching you over…" : "Try it"}
            </button>
            {error && <p role="alert" className="text-xs mt-3" style={{ color: "var(--danger)" }}>{error}</p>}
          </>
        )}
      </main>
    </div>
  );
}
