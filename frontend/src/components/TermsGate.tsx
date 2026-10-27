"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { TERMS_VERSION } from "@/lib/terms";

// Routes where the gate must never appear: the legal pages themselves (so the
// user can actually read what they're agreeing to), the auth flow, and the
// public tokenized pages crew use without an account.
const EXEMPT_PREFIXES = ["/terms", "/privacy", "/auth", "/confirm", "/lunch"];

// Retroactive clickwrap for accounts created before Terms acceptance was
// recorded at signup. Any logged-in user whose metadata lacks
// `terms_accepted_at` must accept (or sign out) before using the app. New
// signups already carry the field, so they never see this.
export default function TermsGate() {
  const pathname = usePathname();
  const router = useRouter();
  const [needsAccept, setNeedsAccept] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);

  const exempt = EXEMPT_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));

  useEffect(() => {
    if (exempt) return;
    let active = true;
    createClient()
      .auth.getUser()
      .then(({ data }) => {
        if (active && data.user && !data.user.user_metadata?.terms_accepted_at) {
          setNeedsAccept(true);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [exempt, pathname]);

  if (exempt || !needsAccept) return null;

  async function handleAccept() {
    setBusy(true);
    try {
      await createClient().auth.updateUser({
        data: { terms_accepted_at: new Date().toISOString(), terms_version: TERMS_VERSION },
      });
      setNeedsAccept(false);
    } catch {
      setBusy(false);
    }
  }

  async function handleSignOut() {
    setBusy(true);
    await createClient().auth.signOut().catch(() => {});
    router.push("/auth/login");
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "var(--scrim)" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="terms-gate-title"
    >
      <div className="card p-6 w-full max-w-md">
        <h3 id="terms-gate-title" className="text-base font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
          Agree to our Terms to continue
        </h3>
        <div className="space-y-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          <p>
            SET&gt;READY is in <strong style={{ color: "var(--text-primary)" }}>early beta</strong> and provided
            &ldquo;as is.&rdquo; Call sheets are generated automatically and can contain mistakes, so always review
            every detail before sending. You&rsquo;re responsible for what you distribute to your crew.
          </p>
          <p>
            We&rsquo;ve added Terms covering this. To keep using your account, please review and accept them.
          </p>
        </div>
        <div className="flex items-start gap-2 mt-4">
          <input
            id="terms-gate-accept"
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            className="mt-0.5 shrink-0"
          />
          <label htmlFor="terms-gate-accept" className="text-xs leading-snug" style={{ color: "var(--text-secondary)" }}>
            I agree to the{" "}
            <Link href="/terms" target="_blank" className="font-medium" style={{ color: "var(--accent-hover)" }}>Terms</Link>
            {" "}and{" "}
            <Link href="/privacy" target="_blank" className="font-medium" style={{ color: "var(--accent-hover)" }}>Privacy Policy</Link>.
          </label>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={handleSignOut} disabled={busy} className="btn btn-ghost">
            Sign out
          </button>
          <button onClick={handleAccept} disabled={busy || !accepted} className="btn btn-primary">
            {busy ? "Saving…" : "Agree & continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
