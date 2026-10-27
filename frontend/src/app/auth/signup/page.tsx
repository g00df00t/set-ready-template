"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

// SET>READY is invite-only during private beta — self-serve signup is disabled
// in Supabase. This page collects invite requests, which email the team via the
// public /api/waitlist endpoint. Approved requesters are invited from the
// Supabase dashboard and accept the Terms on first login (see TermsGate).
export default function RequestInvitePage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await api.post("/api/waitlist", {
        name: name.trim(),
        email: email.trim(),
        note: note.trim() || null,
        website,
      });
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit. Please try again.");
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg-base)" }}>
        <div className="w-full max-w-sm text-center">
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>SET&gt;READY</h1>
          <div className="card p-8 mt-8">
            <p className="text-3xl mb-4">✓</p>
            <p className="text-sm font-medium mb-2" style={{ color: "var(--text-primary)" }}>You&rsquo;re on the list</p>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Thanks for your interest. We&rsquo;re onboarding people gradually during private beta — we&rsquo;ll email{" "}
              <strong style={{ color: "var(--text-primary)" }}>{email}</strong> when a spot opens up.
            </p>
          </div>
          <p className="text-sm text-center mt-5" style={{ color: "var(--text-secondary)" }}>
            Already have an account?{" "}
            <Link href="/auth/login" className="font-medium" style={{ color: "var(--accent-hover)" }}>
              Sign in
            </Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg-base)" }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>SET&gt;READY</h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Private beta — request an invite
          </p>
        </div>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="name" className="field-label">Your name</label>
              <input
                id="name"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="field-input"
                autoComplete="name"
              />
            </div>
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
              <label htmlFor="note" className="field-label">
                What do you shoot? <span style={{ color: "var(--text-secondary)", fontWeight: 400 }}>(optional)</span>
              </label>
              <textarea
                id="note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="field-input"
                rows={3}
                placeholder="e.g. Commercial photography, indie film, branded content…"
              />
            </div>

            {/* Honeypot — hidden from real users, bots tend to fill it */}
            <input
              type="text"
              tabIndex={-1}
              autoComplete="off"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
              style={{ display: "none" }}
              aria-hidden="true"
            />

            {error && <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button type="submit" disabled={loading} className="btn btn-primary w-full">
              {loading ? "Sending…" : "Request an invite"}
            </button>
          </form>
        </div>

        <p className="text-sm text-center mt-5" style={{ color: "var(--text-secondary)" }}>
          Already have an account?{" "}
          <Link href="/auth/login" className="font-medium" style={{ color: "var(--accent-hover)" }}>
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
