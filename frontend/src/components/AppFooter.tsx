import Link from "next/link";
import SupportLink from "@/components/SupportLink";

// Small footer for signed-in app pages so Privacy/Terms/support are reachable
// from inside the product (the marketing footer only lives on the landing page).
export default function AppFooter() {
  const sep = { fontSize: "12px", color: "var(--text-muted)", margin: "0 8px" } as const;
  const link = { fontSize: "12px", color: "var(--text-secondary)", textDecoration: "none" } as const;
  return (
    <footer style={{ borderTop: "1px solid var(--border)", padding: "20px 24px", textAlign: "center" }}>
      <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>SET&gt;READY</span>
      <span style={sep}>·</span>
      <Link href="/privacy" style={link}>Privacy</Link>
      <span style={sep}>·</span>
      <Link href="/terms" style={link}>Terms</Link>
      <span style={sep}>·</span>
      <SupportLink style={link} />
    </footer>
  );
}
