"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { fetchSetupStatus } from "@/lib/setup";

/* Both email-link routes bounce failures back here with ?error= — auth/confirm
 * sends `invalid-link` (invite and recovery token_hash links), auth/callback
 * sends `invalid-reset-link` (the PKCE code exchange). Anything else is a stray
 * param and gets no notice. The value is never rendered, only matched. */
const LINK_ERRORS = new Set(["invalid-link", "invalid-reset-link"]);

/* Arrives as ?signedout=1 from the sign-out buttons, or ?error=… from the links
 * above, so the page can say what just happened instead of presenting a bare
 * form that looks like a session timed out.
 *
 * The error case is the one that strands people. An invited producer has no
 * password yet — the invite link IS their way in — so a link that has expired or
 * already been used drops them on a sign-in form they cannot possibly complete,
 * with nothing on screen explaining why. Forgot password is a genuine way out:
 * resetPasswordForEmail issues a recovery link for an account that has never had
 * a password, and it lands on the same /auth/reset-password screen the invite
 * would have.
 *
 * Split into its own component and wrapped in <Suspense> below because
 * useSearchParams opts the whole subtree into client-side rendering — without a
 * boundary, `next build` fails the page rather than warning. Keeping it to this
 * one line means the form itself still prerenders. */
function StatusNotice() {
  const params = useSearchParams();
  const linkError = params.get("error");
  const signedOut = params.get("signedout") !== null;

  if (linkError === "not-owner") {
    return (
      <div
        className="text-sm text-center mb-5 py-2.5 px-3 rounded-lg"
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--danger)", color: "var(--text-secondary)" }}
        role="alert"
      >
        <p className="font-medium mb-1" style={{ color: "var(--text-primary)" }}>
          This Set Ready belongs to someone else
        </p>
        <p className="text-xs">That account can sign in, but only the owner&rsquo;s account can use this copy.</p>
      </div>
    );
  }

  if (linkError !== null && LINK_ERRORS.has(linkError)) {
    return (
      <div
        className="text-sm text-center mb-5 py-2.5 px-3 rounded-lg"
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--danger)", color: "var(--text-secondary)" }}
        role="alert"
      >
        <p className="font-medium mb-1" style={{ color: "var(--text-primary)" }}>
          That link didn&rsquo;t work
        </p>
        <p className="text-xs">
          It may have expired or already been used.{" "}
          <Link href="/auth/forgot-password" className="font-medium" style={{ color: "var(--accent-hover)" }}>
            Send yourself a new one
          </Link>{" "}
          — this works for a first-time invite too, even if you have never set a password.
        </p>
      </div>
    );
  }

  if (!signedOut) return null;
  return (
    <p
      className="text-sm text-center mb-5 py-2.5 px-3 rounded-lg"
      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
      role="status"
    >
      You&rsquo;re signed out. See you on the next one.
    </p>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // A producer's own copy: no invites, and a copy nobody has claimed yet goes
  // to /setup instead of a sign-in form it can't complete. `null` until the
  // backend answers, so the invite line below neither flashes nor jumps.
  const [ownCopy, setOwnCopy] = useState<boolean | null>(null);

  useEffect(() => {
    fetchSetupStatus()
      .then((s) => {
        setOwnCopy(s.single_owner);
        if (s.single_owner && s.owner_exists === false) router.replace("/setup");
      })
      .catch(() => setOwnCopy(false));
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      setError(error.message);
      setLoading(false);
    } else {
      router.push("/dashboard");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg-base)" }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>SET&gt;READY</h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Plan the day. Tell the crew. Know they got it.
          </p>
        </div>

        <Suspense fallback={null}>
          <StatusNotice />
        </Suspense>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="field-label">Email</label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="field-input"
                autoComplete="email"
              />
            </div>
            <div>
              <label htmlFor="password" className="field-label">Password</label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="field-input"
                autoComplete="current-password"
              />
            </div>
            {error && <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button type="submit" disabled={loading} className="btn btn-primary w-full">
              {loading ? "Signing in…" : "Sign in"}
            </button>
            <p className="text-center">
              <Link href="/auth/forgot-password" className="text-xs" style={{ color: "var(--text-muted)" }}>
                Forgot password?
              </Link>
            </p>
          </form>
        </div>

        {ownCopy === false && (
          <p className="text-sm text-center mt-5" style={{ color: "var(--text-secondary)" }}>
            Invite only during beta.{" "}
            <Link href="/auth/signup" className="font-medium" style={{ color: "var(--accent-hover)" }}>
              Request an invite
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}
