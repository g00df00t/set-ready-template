"use client";

/* The returning user's front door.
 *
 * Reached by typing set-ready-set.com, not by clicking anything — proxy.ts
 * rewrites "/" here when a Supabase auth cookie is present, so the URL stays "/"
 * and the marketing page never renders first. Someone with an account gets their
 * own shoot instead of a pitch for the product they already use.
 *
 * Deliberately NOT a second dashboard. It shows the one thing a producer typing
 * the URL is almost certainly after — their next shoot — and then gets out of the
 * way. Confirmation counts, weather and setup progress all already live on the
 * dashboard and the project overview; duplicating them here would mean two
 * surfaces to keep in sync, which is the bug lib/setupSteps.ts exists to prevent.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";
import { pickNext, isUpcoming, isToday, asDate, type ShootProject } from "@/lib/nextShoot";
import { greeting } from "@/lib/greeting";

function firstName(user: { email?: string; user_metadata?: Record<string, unknown> } | undefined): string | null {
  const meta = user?.user_metadata ?? {};
  const full = (meta.full_name ?? meta.name) as string | undefined;
  if (full?.trim()) return full.trim().split(/\s+/)[0];
  return null;   // an email local-part like "p.kehoe" reads worse than no name
}

export default function WelcomePage() {
  const router = useRouter();
  const [name, setName] = useState<string | null>(null);
  const [next, setNext] = useState<ShootProject | null>(null);
  const [count, setCount] = useState(0);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      // The cookie got us rewritten here, but a cookie is not a valid session.
      // Can't fall back to "/" — the proxy would rewrite it straight back.
      if (!session) { router.replace("/auth/login"); return; }
      setName(firstName(session.user));
      api.get<ShootProject[]>("/api/projects")
        .then((ps) => { setNext(pickNext(ps)); setCount(ps.length); })
        .catch(() => {})           // a failed load just means no shoot card
        .finally(() => setReady(true));
    });
  }, [router]);

  const signOut = useCallback(async () => {
    await createClient().auth.signOut();
    router.push("/auth/login?signedout=1");
  }, [router]);

  // Hold a neutral branded shell rather than flashing either page.
  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg-base)" }}>
      <div className="w-full max-w-sm text-center">
        <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>SET&gt;READY</h1>
        {/* Held until `ready` for the same reason the card below is: the greeting
            depends on whether today is the shoot day, which isn't known until the
            projects load. Showing "Good afternoon" and then swapping it for "Shoot
            day" is exactly the flash this page was built to avoid. The height is
            reserved so nothing moves when it arrives. */}
        <p className="text-sm mb-8" style={{ color: "var(--text-secondary)", minHeight: "1.25rem" }}>
          {ready ? greeting({ name, shootToday: !!next && isToday(next) }) : "\u00A0"}
        </p>

        {!ready ? (
          <div className="card p-6" style={{ minHeight: "132px" }} aria-hidden="true" />
        ) : next ? (
          <>
            <div className="card p-6 text-left">
              <p className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)", letterSpacing: "0.1em" }}>
                {isUpcoming(next) ? "Next shoot" : "Most recent"}
              </p>
              <p className="text-lg font-semibold mb-1" style={{ color: "var(--text-primary)" }}>{next.name}</p>
              <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
                {next.shoot_date
                  ? asDate(next.shoot_date).toLocaleDateString("en-US", {
                      weekday: "long", month: "long", day: "numeric", year: "numeric",
                    })
                  : "No shoot date set"}
              </p>
              <Link href={`/projects/${next.id}`} className="btn btn-primary w-full">
                Open {next.name.length > 22 ? "project" : next.name}
              </Link>
            </div>
            {count > 1 && (
              <p className="text-sm mt-5">
                <Link href="/dashboard" style={{ color: "var(--text-secondary)" }}>
                  All {count} projects
                </Link>
              </p>
            )}
          </>
        ) : (
          <div className="card p-6">
            <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
              You don&rsquo;t have a project yet. Your first call sheet is minutes away.
            </p>
            <Link href="/projects/new" className="btn btn-primary w-full">Create a project</Link>
          </div>
        )}

        <p className="mt-8">
          <button onClick={signOut} className="text-xs" style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }}>
            Sign out
          </button>
        </p>
      </div>
    </div>
  );
}
