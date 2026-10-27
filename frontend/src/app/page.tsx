import Link from "next/link";
import Image from "next/image";
import SupportLink from "@/components/SupportLink";
import LiveConfirmations from "@/components/LiveConfirmations";
import QuickImportDemo from "@/components/QuickImportDemo";

const steps = [
  { n: "1", title: "Create a project", desc: "Name the production, set the shoot date and general call time. Takes 30 seconds." },
  { n: "2", title: "Build your crew list", desc: "Add crew manually or from a saved Roster. Set departments, individual call times, and roles." },
  { n: "3", title: "Set location and schedule", desc: "Enter the address for auto-generated map links. Build the day's schedule with start and end times." },
  { n: "4", title: "Generate the call sheet", desc: "Everything you've entered becomes one formatted, print-ready call sheet — weather, schedule, crew, location, talent. Nothing to lay out, nothing to retype." },
  { n: "5", title: "Send to crew", desc: "One click emails everyone their personal call time and a confirmation link. See who's confirmed in real time." },
];

const features = [
  { name: "One Record, Every Output", tag: "Enter once", desc: "Crew, schedule, location and call times go in once. They become the call sheet, each person's own email, the PDF, and the page they confirm on. Change a call time and all four follow." },
  { name: "Crew Management", tag: "Core", desc: "Department grouping, bulk call time tools, ±15/30/60 min shifts, and per-member confirmation tracking." },
  { name: "The Call Sheet", tag: "One click", desc: "Every detail you've entered, laid out the way crew expect to read it — departments, call times, map links, weather. The same document emails, prints, and exports as PDF." },
  { name: "Email + Confirmation", tag: "SendGrid", desc: "Personalized emails to every crew member. Each gets their call time and a unique confirmation link." },
  { name: "Master Roster", tag: "Cross-project", desc: "Persistent crew, talent, and client database. Add once, pull into any project." },
  { name: "Your Data, Protected", tag: "Private", desc: "Crew names, numbers, and locations stay locked to your account and encrypted. The info your team trusts you with stays safe." },
];

const trust = [
  { title: "Locked to your account", desc: "Your projects, crew, and contacts are visible only to you — enforced at the database level, not just in the app. No other user can reach your data." },
  { title: "Encrypted in transit and at rest", desc: "Every connection is secured over HTTPS, and your data is encrypted where it's stored. Standard practice, done right." },
  { title: "Confirmation links can't be guessed", desc: "The links crew use to confirm carry long, random tokens that can't be enumerated, backed by rate limits that block abuse." },
  { title: "Erase everything in one click", desc: "Delete your account and every project, contact, and call sheet is permanently removed — no waiting, no email back-and-forth." },
];

export default function Home() {
  return (
    <div style={{ background: "var(--bg-base)", color: "var(--text-primary)", minHeight: "100vh" }}>

      {/* ── Nav ── */}
      <nav style={{ borderBottom: "1px solid var(--border)", position: "sticky", top: 0, zIndex: 50, background: "var(--bg-base)" }}>
        <div style={{ maxWidth: "1100px", margin: "0 auto", padding: "0 24px", height: "56px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontWeight: 800, fontSize: "14px", letterSpacing: "0.04em" }}>SET&gt;READY</span>
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <Link href="/auth/login" style={{ fontSize: "14px", color: "var(--text-secondary)", textDecoration: "none" }}>
              Sign in
            </Link>
            <Link href="/auth/signup" className="btn btn-primary btn-sm">
              Request an invite
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section style={{ padding: "80px 24px 0" }}>
        <div style={{ maxWidth: "800px", margin: "0 auto", textAlign: "center" }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: "8px",
            fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em",
            color: "var(--accent-text)", background: "var(--accent-subtle)",
            padding: "4px 14px", borderRadius: "999px", marginBottom: "36px",
          }}>
            Private beta · Invite only
          </div>

          <h1 style={{
            fontSize: "clamp(40px, 7vw, 76px)", fontWeight: 800,
            lineHeight: 1.04, letterSpacing: "-0.035em", marginBottom: "24px",
          }}>
            The shoot-day<br />
            <span style={{ color: "var(--accent-hover)" }}>command center</span><br />
            for producers.
          </h1>

          <p style={{
            fontSize: "18px", color: "var(--text-secondary)", lineHeight: 1.7,
            maxWidth: "520px", margin: "0 auto 40px",
          }}>
            Add your crew, schedule, and location — SET&gt;READY generates a professional call sheet, sends it to everyone in minutes, and tracks every confirmation as it lands.
          </p>

          <div style={{ display: "flex", gap: "12px", justifyContent: "center", flexWrap: "wrap" }}>
            <Link href="/auth/signup" className="btn btn-primary" style={{ fontSize: "15px", padding: "11px 28px" }}>
              Request an invite
            </Link>
            <Link href="/auth/login" className="btn btn-secondary" style={{ fontSize: "15px", padding: "11px 28px" }}>
              Sign in
            </Link>
          </div>
        </div>

        {/* Dashboard screenshot */}
        <div style={{ maxWidth: "1100px", margin: "64px auto 0", padding: "0 24px" }}>
          <div style={{
            border: "1px solid var(--border)", borderRadius: "12px", overflow: "hidden",
            boxShadow: "0 0 80px rgba(99,102,241,0.10), 0 32px 64px rgba(0,0,0,0.4)",
          }}>
            {/* Browser chrome */}
            <div style={{
              background: "var(--bg-surface)", padding: "10px 16px",
              borderBottom: "1px solid var(--border)",
              display: "flex", alignItems: "center", gap: "6px",
            }}>
              <span style={{ width: "11px", height: "11px", borderRadius: "50%", background: "#ff5f56", display: "inline-block" }} />
              <span style={{ width: "11px", height: "11px", borderRadius: "50%", background: "#ffbd2e", display: "inline-block" }} />
              <span style={{ width: "11px", height: "11px", borderRadius: "50%", background: "#27c93f", display: "inline-block" }} />
            </div>
            {/* Two images, one CSS toggle keyed off the same html[data-theme]
                attribute everything else on this page already uses (set
                before hydration in layout.tsx, so there's no flash) — a
                static screenshot can't otherwise follow the visitor's
                stored theme preference the way every other themed element
                on this page does. */}
            <Image
              src="/screenshots/dashboard.png"
              width={3066}
              height={1788}
              priority
              sizes="(max-width: 1100px) 100vw, 1052px"
              alt="SET>READY production overview dashboard"
              className="hero-shot hero-shot-dark"
              style={{ width: "100%", height: "auto" }}
            />
            <Image
              src="/screenshots/dashboard-light.png"
              width={2000}
              height={1003}
              priority
              sizes="(max-width: 1100px) 100vw, 1052px"
              alt="SET>READY production overview dashboard"
              className="hero-shot hero-shot-light"
              style={{ width: "100%", height: "auto" }}
            />
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section style={{ padding: "80px 24px 96px" }}>
        <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
          <div className="grid grid-cols-1 md:grid-cols-2" style={{ gap: "64px", alignItems: "start" }}>
            <div>
              <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--accent-text)", marginBottom: "12px" }}>
                How it works
              </div>
              <h2 style={{ fontSize: "clamp(28px, 4vw, 48px)", fontWeight: 800, letterSpacing: "-0.025em", lineHeight: 1.1, marginBottom: "20px" }}>
                One tool.<br />Shoot day,<br />start to finish.
              </h2>
              <p style={{ fontSize: "15px", color: "var(--text-secondary)", lineHeight: 1.75, maxWidth: "360px" }}>
                From project to sent call sheet in under 10 minutes. Each page hands you to the next and finished steps fold away, so you always know what is left to do.
              </p>

              {/* Live confirmations proof */}
              <LiveConfirmations />
            </div>

            <div>
              {steps.map((s, i) => (
                <div key={s.n} style={{
                  display: "flex", gap: "16px",
                  paddingBottom: i < steps.length - 1 ? "72px" : 0,
                  marginBottom: i < steps.length - 1 ? "72px" : 0,
                  borderBottom: i < steps.length - 1 ? "1px solid var(--border)" : "none",
                }}>
                  <div style={{
                    width: "28px", height: "28px", borderRadius: "50%",
                    background: "var(--accent)", color: "#fff",
                    fontSize: "12px", fontWeight: 700,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    flexShrink: 0, marginTop: "2px",
                  }}>
                    {s.n}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: "4px", fontSize: "14px" }}>{s.title}</div>
                    <div style={{ fontSize: "13px", color: "var(--text-secondary)", lineHeight: 1.65 }}>{s.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Quick Import spotlight ── */}
      <section style={{ padding: "16px 24px 96px" }}>
        <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
          <div className="grid grid-cols-1 md:grid-cols-2" style={{ gap: "64px", alignItems: "center" }}>
            <div>
              <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--accent-text)", marginBottom: "12px" }}>
                Quick Import
              </div>
              <h2 style={{ fontSize: "clamp(28px, 4vw, 48px)", fontWeight: 800, letterSpacing: "-0.025em", lineHeight: 1.1, marginBottom: "20px" }}>
                Already have a<br />call sheet?<br />Paste it in.
              </h2>
              <p style={{ fontSize: "15px", color: "var(--text-secondary)", lineHeight: 1.75, maxWidth: "380px" }}>
                Copy crew straight from an old PDF, spreadsheet, or email — however messy. Names, roles, emails, and phone numbers come out clean and structured in seconds. No retyping, no reformatting.
              </p>
            </div>

            <div style={{ display: "flex", justifyContent: "center" }}>
              <QuickImportDemo />
            </div>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section style={{ padding: "80px 24px 96px" }}>
        <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
          <div style={{ marginBottom: "48px" }}>
            <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--accent-text)", marginBottom: "12px" }}>
              Features
            </div>
            <h2 style={{ fontSize: "clamp(28px, 4vw, 48px)", fontWeight: 800, letterSpacing: "-0.025em", lineHeight: 1.1 }}>
              Everything a producer needs.<br />Nothing they don't.
            </h2>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "16px" }}>
            {features.map((f) => (
              <div key={f.name} style={{
                background: "var(--bg-surface)", border: "1px solid var(--border)",
                borderRadius: "12px", overflow: "hidden",
              }}>
                <div style={{
                  padding: "12px 16px", background: "var(--bg-elevated)",
                  borderBottom: "1px solid var(--border)",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                }}>
                  <span style={{ fontWeight: 700, fontSize: "14px" }}>{f.name}</span>
                  <span style={{
                    fontSize: "11px", color: "var(--accent-text)",
                    background: "var(--accent-subtle)",
                    padding: "2px 8px", borderRadius: "4px",
                    fontFamily: "var(--font-mono)",
                  }}>
                    {f.tag}
                  </span>
                </div>
                <div style={{ padding: "16px", fontSize: "13px", color: "var(--text-secondary)", lineHeight: 1.7 }}>
                  {f.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Security & privacy ── */}
      <section style={{ padding: "0 24px 96px" }}>
        <div style={{
          maxWidth: "1100px", margin: "0 auto",
          background: "var(--bg-surface)", border: "1px solid var(--border)",
          borderRadius: "16px", padding: "56px 48px",
        }}>
          <div style={{ maxWidth: "560px", marginBottom: "44px" }}>
            <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", color: "var(--accent-text)", marginBottom: "12px" }}>
              Security &amp; privacy
            </div>
            <h2 style={{ fontSize: "clamp(28px, 4vw, 44px)", fontWeight: 800, letterSpacing: "-0.025em", lineHeight: 1.1, marginBottom: "20px" }}>
              Your crew&apos;s data, kept safe.
            </h2>
            <p style={{ fontSize: "15px", color: "var(--text-secondary)", lineHeight: 1.75 }}>
              Names, emails, phone numbers, shoot locations — your crew trusts you with all of it. SET&gt;READY is built so that trust holds.
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "28px 40px" }}>
            {trust.map((t) => (
              <div key={t.title} style={{ display: "flex", gap: "14px" }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-hover)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: "1px" }} aria-hidden="true">
                  <path d="M9 12l2 2 4-4" />
                  <path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z" />
                </svg>
                <div>
                  <div style={{ fontWeight: 600, fontSize: "14px", marginBottom: "5px" }}>{t.title}</div>
                  <div style={{ fontSize: "13px", color: "var(--text-secondary)", lineHeight: 1.7 }}>{t.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={{ padding: "80px 24px 96px" }}>
        <div style={{
          maxWidth: "600px", margin: "0 auto", textAlign: "center",
          background: "var(--bg-surface)", border: "1px solid var(--border)",
          borderRadius: "16px", padding: "64px 40px",
        }}>
          <h2 style={{ fontSize: "clamp(26px, 4vw, 40px)", fontWeight: 800, letterSpacing: "-0.025em", marginBottom: "16px" }}>
            Ready to run a better shoot?
          </h2>
          <p style={{ fontSize: "16px", color: "var(--text-secondary)", marginBottom: "32px", lineHeight: 1.7 }}>
            SET&gt;READY is in private beta and free while we onboard producers gradually. Request an invite and we&apos;ll reach out when a spot opens.
          </p>
          <Link href="/auth/signup" className="btn btn-primary" style={{ fontSize: "15px", padding: "12px 32px" }}>
            Request an invite
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer style={{ borderTop: "1px solid var(--border)", padding: "24px", textAlign: "center" }}>
        <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>SET&gt;READY · 2026</span>
        <span style={{ fontSize: "12px", color: "var(--text-muted)", margin: "0 8px" }}>·</span>
        <Link href="/privacy" style={{ fontSize: "12px", color: "var(--text-secondary)", textDecoration: "none" }}>Privacy</Link>
        <span style={{ fontSize: "12px", color: "var(--text-muted)", margin: "0 8px" }}>·</span>
        <Link href="/terms" style={{ fontSize: "12px", color: "var(--text-secondary)", textDecoration: "none" }}>Terms</Link>
        <span style={{ fontSize: "12px", color: "var(--text-muted)", margin: "0 8px" }}>·</span>
        <SupportLink style={{ fontSize: "12px", color: "var(--text-secondary)", textDecoration: "none" }} />
      </footer>

    </div>
  );
}
