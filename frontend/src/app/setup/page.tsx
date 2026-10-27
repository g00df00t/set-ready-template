"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { createOwner, fetchSetupStatus } from "@/lib/setup";

// The first screen a producer's own copy shows: make the account that owns it.
// Reached from /auth/login when the backend says this is a copy with no owner
// yet; otherwise it bounces back there. One account, created once — after this
// the backend turns away every other sign-in (auth.get_current_user).
export default function SetupPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchSetupStatus()
      .then((s) => {
        if (s.single_owner && s.owner_exists === false) setReady(true);
        else router.replace("/auth/login");
      })
      .catch(() => router.replace("/auth/login"));
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== again) {
      setError("The two passwords don't match.");
      return;
    }
    setLoading(true);
    try {
      await createOwner({ name: name.trim(), email: email.trim(), password });
      const { error } = await createClient().auth.signInWithPassword({ email: email.trim(), password });
      if (error) throw new Error(error.message);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the account. Please try again.");
      setLoading(false);
    }
  }

  if (!ready) return null;

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg-base)" }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>SET&gt;READY</h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            This copy is yours. Make the account that owns it.
          </p>
        </div>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="name" className="field-label">Your name</label>
              <input id="name" type="text" required value={name} onChange={(e) => setName(e.target.value)}
                     className="field-input" autoComplete="name" />
            </div>
            <div>
              <label htmlFor="email" className="field-label">Email</label>
              <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                     className="field-input" autoComplete="email" />
            </div>
            <div>
              <label htmlFor="password" className="field-label">Password</label>
              <input id="password" type="password" required minLength={8} value={password}
                     onChange={(e) => setPassword(e.target.value)} className="field-input" autoComplete="new-password" />
            </div>
            <div>
              <label htmlFor="again" className="field-label">Password again</label>
              <input id="again" type="password" required minLength={8} value={again}
                     onChange={(e) => setAgain(e.target.value)} className="field-input" autoComplete="new-password" />
            </div>
            {error && <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button type="submit" disabled={loading} className="btn btn-primary w-full">
              {loading ? "Setting up…" : "Create my account"}
            </button>
          </form>
        </div>

        <p className="text-xs text-center mt-5" style={{ color: "var(--text-muted)" }}>
          Only one account can be made here. After this, sign in at the usual page.
        </p>
      </div>
    </div>
  );
}
