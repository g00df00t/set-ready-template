import type { Metadata } from "next";
import { API_BASE } from "@/lib/apiBase";

interface Props {
  params: Promise<{ token: string }>;
}

interface SharedWrap {
  project_name: string;
  shoot_date: string | null;
  html: string;
}

/**
 * The public wrap report — no account, no auth. The token is the access control,
 * the same bargain /confirm/[token] makes.
 *
 * Rendered on the server so the HTML arrives with the page rather than after a
 * round trip; whoever opens this is a client or a production company, not
 * someone who will wait through a spinner to see whether the link works.
 */
async function fetchReport(token: string): Promise<SharedWrap | null> {
  // A throw here — an unreachable API, an unset base URL — must land on the
  // same "link not recognised" page as a bad token, not on a 500.
  try {
    const res = await fetch(`${API_BASE}/api/wrap/${token}`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// Nothing shared should end up in a search index. A producer pasting this into
// an email has not agreed to publish their crew list.
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default async function SharedWrapPage({ params }: Props) {
  const { token } = await params;
  const report = await fetchReport(token);

  if (!report) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "24px", background: "#0e1420" }}>
        <div style={{ textAlign: "center" }}>
          <h1 style={{ fontSize: "1.1rem", fontWeight: 600, color: "#eef2f8", marginBottom: "6px" }}>Link not recognised</h1>
          {/* Deliberately vague. Saying "this link was revoked" would confirm
              the shoot exists to anyone holding a dead URL. */}
          <p style={{ fontSize: "0.875rem", color: "#7c8798" }}>This link may be invalid, or it may have been turned off.</p>
        </div>
      </div>
    );
  }

  return (
    // No background of its own: .wrap-report paints its own ground and flips
    // with the viewer's theme, so hardcoding one here would put a light report
    // on a dark page for anyone whose browser remembers light mode.
    <div style={{ minHeight: "100vh", padding: "0 16px 40px" }}>
      <div style={{ maxWidth: "980px", margin: "0 auto" }} dangerouslySetInnerHTML={{ __html: report.html }} />
    </div>
  );
}
