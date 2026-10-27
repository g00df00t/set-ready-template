import { FitSheet } from "@/components/FitSheet";
import { TitleCard } from "@/components/TitleCard";
import { isBrandColor } from "@/lib/brand";
import { API_BASE } from "@/lib/apiBase";
import { ConfirmCard } from "./ConfirmCard";

interface Props {
  params: Promise<{ token: string }>;
}

interface ConfirmData {
  confirmed: boolean;
  already_confirmed?: boolean;
  name: string | null;
  call_time: string | null;
  call_sheet_html: string | null;
  /** The producer's company, from the API — this page has no session, and the
   *  person opening it has no account. */
  brand?: { name: string | null; accent: string | null; image_url?: string | null; image_has_name?: boolean };
}

function fmtTime(t: string): string {
  // The API sends "HH:MM:SS", or the producer's own call-time note ("7am,
  // after the move") as typed — which must print as written, not as "NaN".
  if (!/^\d{1,2}:\d{2}/.test(t)) return t;
  const [h, m] = t.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${ampm}`;
}

export default async function ConfirmPage({ params }: Props) {
  const { token } = await params;

  // Never throws. A crew member standing on a call sheet's confirm link at
  // 5am gets a page that explains itself, not a 500 — whatever is wrong with
  // the API, the network, or the environment.
  let data: ConfirmData = { confirmed: false, name: null, call_time: null, call_sheet_html: null };
  try {
    const res = await fetch(`${API_BASE}/api/confirm/${token}`, { cache: "no-store" });
    if (res.ok) data = await res.json();
  } catch {
    // Falls through to the not-recognised state below.
  }

  if (!data.confirmed) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "24px", background: "#0d1117" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: "2rem", marginBottom: "12px", color: "#445166" }}>✗</div>
          <h1 style={{ fontSize: "1.1rem", fontWeight: 600, color: "#e8edf5", marginBottom: "6px" }}>Link not recognised</h1>
          <p style={{ fontSize: "0.875rem", color: "#7d8fa3" }}>This confirmation link may be invalid or expired.</p>
        </div>
      </div>
    );
  }

  const brandName = data.brand?.name;
  const brandAccent = isBrandColor(data.brand?.accent) ? data.brand!.accent : null;

  return (
    <div style={{ minHeight: "100vh", background: "#0d1117", fontFamily: "system-ui, -apple-system, Arial, sans-serif" }}>

      {/* Whose sheet this is, before anything else on the page. Deliberately a
          card of its own rather than a recolouring of the banner below: white
          text on an arbitrary brand colour is a contrast problem with no good
          answer, and a title card is what this was asked to be anyway. */}
      {brandName && (
        <div style={{ maxWidth: "680px", margin: "0 auto", padding: "20px 16px 0" }}>
          <TitleCard name={brandName} accent={brandAccent} image={data.brand?.image_url} nameInImage={data.brand?.image_has_name} kind="Call sheet" />
        </div>
      )}

      {/* Call time, and the "Got it" that confirms — opening the link alone
          no longer does (see ConfirmCard). */}
      <ConfirmCard
        token={token}
        apiBase={API_BASE}
        name={data.name}
        callTime={data.call_time ? fmtTime(data.call_time) : null}
        alreadyConfirmed={!!data.already_confirmed}
      />

      {/* Call sheet */}
      {data.call_sheet_html && (
        <div style={{ padding: "24px 16px 48px" }}>
          <p style={{ fontSize: "11px", fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: "#445166", textAlign: "center", marginBottom: "16px" }}>
            Full Call Sheet
          </p>
          <FitSheet html={data.call_sheet_html} />
          <p style={{ fontSize: "11px", color: "#445166", textAlign: "center", marginTop: "10px" }}>
            Pinch to zoom in
          </p>
        </div>
      )}
    </div>
  );
}
