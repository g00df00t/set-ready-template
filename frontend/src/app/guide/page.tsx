import Link from "next/link";

const STEPS = [
  {
    title: "Create a project",
    body: 'From your dashboard, click "New project." Give it a name and set your shoot date. Takes about 30 seconds.',
  },
  {
    title: "Add your crew",
    body: "Go to Crew in the sidebar. Add crew members one at a time, pick from your saved Roster, or paste text directly from a Google Sheet, Excel file, or any contact list — SET>READY uses AI to extract names, roles, emails, and phone numbers automatically.",
    tip: "Include a call time for each crew member. They'll receive their personal call time on the call sheet.",
  },
  {
    title: "Add talent",
    body: "Go to Talent. Add on-camera talent the same way — manual entry or paste from a spreadsheet. Names and roles appear in a dedicated talent section on the call sheet.",
  },
  {
    title: "Add agency & client contacts",
    body: "Go to Agency & Client. Add anyone who should receive the call sheet — creative directors, art buyers, brand contacts. Their emails receive a copy automatically when you send.",
  },
  {
    title: "Set your location",
    body: "Go to Location. Enter the shoot address and any parking or access notes. SET>READY generates Apple Maps and Google Maps links that appear directly on the call sheet.",
  },
  {
    title: "Build your schedule",
    body: "Go to Schedule. Add items with start and end times — crew call, hair & makeup, first talent on set, lunch, wrap. These appear on the call sheet in order.",
  },
  {
    title: "Preview your call sheet",
    body: 'Go to Call Sheet and click "Preview Call Sheet." A formatted, print-ready call sheet is built instantly — crew by department, talent section, schedule, location with map links, and shoot-day weather.',
    tip: "Refresh the call sheet as many times as you like before sending.",
  },
  {
    title: "Send to crew",
    body: 'Click "Send." Every crew member, talent, and contact receives a personalized email. Crew get their individual call time plus a one-click confirmation link. Track who\'s confirmed in real time on the Production Overview.',
  },
];

const TIPS = [
  {
    label: "Paste import",
    body: "Copy and paste rows from any spreadsheet or document. However it's formatted, names, roles, and contact info are pulled out automatically.",
  },
  {
    label: "Master Roster",
    body: "Crew and talent you add are saved to your Roster automatically. On future projects, pick from Roster instead of re-entering contacts.",
  },
  {
    label: "Duplicate projects",
    body: "From the dashboard, duplicate any past project to reuse its crew list, location, and schedule as a starting point.",
  },
  {
    label: "Confirmation tracking",
    body: "The Production Overview shows a live confirmation rate as crew click the link in their email.",
  },
  {
    label: "PDF",
    body: "Use your browser's Print function on the Call Sheet page to download or print as PDF.",
  },
];

export default function GuidePage() {
  return (
    <div style={{ background: "var(--bg-base)", minHeight: "100vh" }}>
      {/* Header */}
      <header
        style={{
          background: "var(--bg-sidebar)",
          backdropFilter: "var(--blur)",
          WebkitBackdropFilter: "var(--blur)",
          borderBottom: "1px solid var(--border)",
          padding: "0 24px",
          height: "52px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          position: "sticky",
          top: 0,
          zIndex: 10,
        }}
      >
        <span
          style={{
            fontSize: "14px",
            fontWeight: 700,
            letterSpacing: "-0.01em",
            color: "var(--text-primary)",
          }}
        >
          SET&gt;READY
        </span>
        <Link
          href="/auth/signup"
          style={{
            fontSize: "13px",
            fontWeight: 600,
            color: "var(--accent)",
            textDecoration: "none",
          }}
        >
          Get started →
        </Link>
      </header>

      <main style={{ maxWidth: "660px", margin: "0 auto", padding: "60px 24px 80px" }}>
        {/* Hero */}
        <div style={{ marginBottom: "52px" }}>
          <p
            style={{
              fontSize: "11px",
              fontWeight: 700,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "var(--accent)",
              marginBottom: "16px",
            }}
          >
            User Guide
          </p>
          <h1
            style={{
              fontSize: "34px",
              fontWeight: 700,
              lineHeight: 1.2,
              color: "var(--text-primary)",
              marginBottom: "16px",
            }}
          >
            Build and send a professional call sheet in minutes.
          </h1>
          <p style={{ fontSize: "16px", lineHeight: 1.65, color: "var(--text-secondary)" }}>
            SET&gt;READY handles the logistics so you can focus on the shoot. Here&apos;s
            everything you need to know to get your first call sheet out the door.
          </p>
        </div>

        {/* Steps */}
        <div style={{ marginBottom: "52px" }}>
          {STEPS.map((step, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                gap: "20px",
                padding: "24px 0",
                borderBottom:
                  i < STEPS.length - 1 ? "1px solid var(--border)" : "none",
              }}
            >
              <div
                style={{
                  width: "30px",
                  height: "30px",
                  borderRadius: "50%",
                  background: "var(--accent)",
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "12px",
                  fontWeight: 700,
                  flexShrink: 0,
                  marginTop: "2px",
                }}
              >
                {i + 1}
              </div>
              <div>
                <h2
                  style={{
                    fontSize: "16px",
                    fontWeight: 600,
                    color: "var(--text-primary)",
                    marginBottom: "8px",
                  }}
                >
                  {step.title}
                </h2>
                <p
                  style={{
                    fontSize: "14px",
                    lineHeight: 1.65,
                    color: "var(--text-secondary)",
                  }}
                >
                  {step.body}
                </p>
                {step.tip && (
                  <p
                    style={{
                      fontSize: "13px",
                      marginTop: "10px",
                      color: "var(--text-muted)",
                      fontStyle: "italic",
                    }}
                  >
                    {step.tip}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Tips */}
        <div
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            borderRadius: "12px",
            padding: "28px",
            marginBottom: "48px",
          }}
        >
          <p
            style={{
              fontSize: "11px",
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: "20px",
            }}
          >
            Tips
          </p>
          {TIPS.map((tip, i) => (
            <div key={i} style={{ marginBottom: i < TIPS.length - 1 ? "18px" : 0 }}>
              <p
                style={{
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "var(--text-primary)",
                  marginBottom: "4px",
                }}
              >
                {tip.label}
              </p>
              <p style={{ fontSize: "14px", lineHeight: 1.6, color: "var(--text-secondary)" }}>
                {tip.body}
              </p>
            </div>
          ))}
        </div>

        {/* CTA */}
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: "12px",
            padding: "36px 32px",
            textAlign: "center",
          }}
        >
          <p
            style={{
              fontSize: "22px",
              fontWeight: 700,
              color: "var(--text-primary)",
              marginBottom: "10px",
            }}
          >
            Ready to get started?
          </p>
          <p
            style={{
              fontSize: "14px",
              color: "var(--text-secondary)",
              marginBottom: "24px",
            }}
          >
            SET&gt;READY is in private beta — request an invite and we&apos;ll reach out when a spot opens.
          </p>
          <Link
            href="/auth/signup"
            style={{
              display: "inline-block",
              background: "var(--accent)",
              color: "#fff",
              fontSize: "14px",
              fontWeight: 600,
              padding: "10px 28px",
              borderRadius: "8px",
              textDecoration: "none",
            }}
          >
            Request an invite
          </Link>
        </div>
      </main>
    </div>
  );
}
