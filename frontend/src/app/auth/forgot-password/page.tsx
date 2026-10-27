"use client";

import { useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    const supabase = createClient();
    const redirectTo = `${window.location.origin}/auth/callback?next=/auth/reset-password`;
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo });
    if (error) {
      setError(error.message);
      setLoading(false);
    } else {
      setSent(true);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg-base)" }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>SET&gt;READY</h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>Reset your password</p>
        </div>

        <div className="card p-6">
          {sent ? (
            <div className="text-center space-y-3">
              <div className="text-2xl" style={{ color: "var(--success)" }}>✓</div>
              <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>Check your email</p>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                We sent a password reset link to <strong>{email}</strong>. It may take a minute to arrive.
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                Enter your email and we&apos;ll send you a link to reset your password.
              </p>
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
              {error && <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
              <button type="submit" disabled={loading} className="btn btn-primary w-full">
                {loading ? "Sending…" : "Send reset link"}
              </button>
            </form>
          )}
        </div>

        <p className="text-sm text-center mt-5" style={{ color: "var(--text-secondary)" }}>
          <Link href="/auth/login" className="font-medium" style={{ color: "var(--accent-hover)" }}>
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
