"use client";

// The top of the public confirm page. Opening the link shows the crew member
// their call time; pressing "Got it" is what confirms them (POST). It used to
// confirm on page load, which let email scanners and chat link previews
// confirm people who'd never seen the message — see backend
// routers/call_sheet.py. Fixed palette, like the rest of this page: no
// session, no theme.

import { useState } from "react";

interface Props {
  token: string;
  apiBase: string;
  name: string | null;
  callTime: string | null;
  alreadyConfirmed: boolean;
}

export function ConfirmCard({ token, apiBase, name, callTime, alreadyConfirmed }: Props) {
  const [state, setState] = useState<"ask" | "saving" | "done" | "error">(alreadyConfirmed ? "done" : "ask");
  const confirmedNow = state === "done" && !alreadyConfirmed;

  async function confirm() {
    if (state === "saving") return;
    setState("saving");
    try {
      const res = await fetch(`${apiBase}/api/confirm/${token}`, { method: "POST" });
      const data = res.ok ? await res.json() : null;
      setState(data?.confirmed ? "done" : "error");
    } catch {
      setState("error");
    }
  }

  const done = state === "done";

  return (
    <div style={{ background: "#1e3359", padding: "48px 24px 40px", textAlign: "center" }}>
      <p style={{ fontSize: "11px", fontWeight: 700, letterSpacing: "0.1em", color: "rgba(255,255,255,0.35)", marginBottom: "24px", textTransform: "uppercase" }}>
        SET&gt;READY
      </p>

      {done && (
        <div style={{
          width: "52px", height: "52px", borderRadius: "50%",
          background: "rgba(255,255,255,0.12)", display: "flex",
          alignItems: "center", justifyContent: "center",
          margin: "0 auto 16px", fontSize: "22px", color: "#fff",
        }}>✓</div>
      )}

      <h1 style={{ fontSize: "1.25rem", fontWeight: 700, color: "#fff", marginBottom: "4px" }}>
        {done ? (confirmedNow ? "You're confirmed" : "Already confirmed")
          : name ? `Hi ${name.split(" ")[0]}` : "Your call sheet"}
      </h1>

      {name && (
        <p style={{ fontSize: "0.875rem", color: "rgba(255,255,255,0.5)", marginBottom: "28px" }}>
          {done ? name : "Here's your call time for the day."}
        </p>
      )}

      {callTime && (
        <div style={{ marginTop: name ? "0" : "28px" }}>
          <p style={{ fontSize: "11px", fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.4)", marginBottom: "6px" }}>
            Your call time
          </p>
          <p style={{ fontSize: "clamp(3rem, 15vw, 5rem)", fontWeight: 800, color: "#fff", lineHeight: 1, letterSpacing: "-2px" }}>
            {callTime}
          </p>
        </div>
      )}

      {!done && (
        <div style={{ marginTop: "32px" }}>
          <button
            type="button"
            onClick={confirm}
            disabled={state === "saving"}
            style={{
              background: "#fff", color: "#1e3359", border: 0, borderRadius: "999px",
              padding: "14px 32px", fontSize: "1rem", fontWeight: 700, cursor: "pointer",
              opacity: state === "saving" ? 0.7 : 1, minWidth: "220px",
            }}
          >
            {state === "saving" ? "Confirming…" : "Got it — confirm"}
          </button>
          <p style={{ fontSize: "0.8125rem", color: "rgba(255,255,255,0.5)", marginTop: "12px" }}>
            {state === "error"
              ? "That didn't go through. Check your connection and try again."
              : "Lets production know you have the call sheet."}
          </p>
        </div>
      )}
    </div>
  );
}
