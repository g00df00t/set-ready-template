import Link from "next/link";

// Shared chrome for the static legal pages (Privacy, Terms). The root layout
// already provides the <main> landmark, so this uses a plain wrapper.
export default function LegalPage({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ background: "var(--bg-base)", color: "var(--text-primary)", minHeight: "100vh" }}>
      <nav style={{ borderBottom: "1px solid var(--border)" }}>
        <div style={{ maxWidth: "760px", margin: "0 auto", padding: "0 24px", height: "56px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Link href="/" style={{ fontWeight: 800, fontSize: "14px", letterSpacing: "0.04em", color: "var(--text-primary)", textDecoration: "none" }}>
            SET&gt;READY
          </Link>
          <Link href="/" style={{ fontSize: "14px", color: "var(--text-secondary)", textDecoration: "none" }}>
            ← Back to home
          </Link>
        </div>
      </nav>

      <div style={{ maxWidth: "760px", margin: "0 auto", padding: "48px 24px 80px" }}>
        <h1 style={{ fontSize: "32px", fontWeight: 800, letterSpacing: "-0.02em", marginBottom: "8px" }}>{title}</h1>
        <p style={{ fontSize: "13px", color: "var(--text-muted)", marginBottom: "8px" }}>Last updated: {updated}</p>
        <p style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "32px", fontStyle: "italic" }}>
          This document is provided for general information and is not legal advice.
        </p>
        <div className="legal">{children}</div>

        <div style={{ marginTop: "48px", paddingTop: "24px", borderTop: "1px solid var(--border)", display: "flex", gap: "20px", fontSize: "13px" }}>
          <Link href="/privacy" style={{ color: "var(--text-secondary)", textDecoration: "none" }}>Privacy Policy</Link>
          <Link href="/terms" style={{ color: "var(--text-secondary)", textDecoration: "none" }}>Terms of Service</Link>
          <Link href="/" style={{ color: "var(--text-secondary)", textDecoration: "none" }}>Home</Link>
        </div>
      </div>
    </div>
  );
}
