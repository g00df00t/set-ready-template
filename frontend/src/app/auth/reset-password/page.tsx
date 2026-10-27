"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const supabase = createClient();

    // Check for a session that the callback route already established
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) setReady(true);
    });

    // Also listen for the PASSWORD_RECOVERY event (fires when Supabase processes
    // the recovery token from the URL hash on direct email link clicks)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY" && session) {
        setReady(true);
        setError("");
      }
    });

    const timer = setTimeout(() => {
      setReady((r) => {
        if (!r) setError("Invalid or expired reset link. Please request a new one.");
        return r;
      });
    }, 3000);

    return () => {
      subscription.unsubscribe();
      clearTimeout(timer);
    };
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) { setError("Passwords don't match."); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters."); return; }
    setLoading(true); setError("");
    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ password });
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
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>Choose a new password</p>
        </div>

        <div className="card p-6">
          {!ready && error ? (
            <div className="text-center space-y-3">
              <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>
              <a href="/auth/forgot-password" className="text-xs" style={{ color: "var(--accent)" }}>
                Request a new reset link
              </a>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="new-password" className="field-label">New password</label>
                <input
                  id="new-password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="field-input"
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label htmlFor="confirm-password" className="field-label">Confirm password</label>
                <input
                  id="confirm-password"
                  type="password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="field-input"
                  autoComplete="new-password"
                />
              </div>
              {error && <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
              <button type="submit" disabled={loading || !ready} className="btn btn-primary w-full">
                {loading ? "Saving…" : "Set new password"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
