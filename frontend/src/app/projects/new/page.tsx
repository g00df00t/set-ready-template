"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import AppFooter from "@/components/AppFooter";
import { DateInput } from "@/components/DateInput";

export default function NewProjectPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [shootDate, setShootDate] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const project = await api.post<{ id: string }>("/api/projects", {
        name,
        shoot_date: shootDate || null,
      });
      router.push(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="px-6 py-3"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <Link href="/dashboard" className="text-xs" style={{ color: "var(--text-secondary)" }}>
          ← Dashboard
        </Link>
      </header>

      <main className="flex-1 w-full max-w-md mx-auto px-6 py-12">
        <h2 className="text-xl font-semibold mb-8" style={{ color: "var(--text-primary)" }}>
          New project
        </h2>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="field-label">Project name</label>
              <input
                type="text"
                required
                aria-label="Project name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Spring campaign shoot — Day 1"
                className="field-input"
              />
            </div>
            <div>
              <label className="field-label">Shoot date</label>
              <DateInput
                ariaLabel="Shoot date"
                value={shootDate}
                onChange={setShootDate}
                min="2000-01-01"
                max="2100-12-31"
              />
            </div>
            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button type="submit" disabled={loading} className="btn btn-primary w-full">
              {loading ? "Creating…" : "Create project"}
            </button>
          </form>
        </div>
      </main>
      <AppFooter />
    </div>
  );
}
