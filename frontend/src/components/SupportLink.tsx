"use client";

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";

export default function SupportLink({
  label = "Need help?",
  className,
  style,
}: {
  label?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [mounted, setMounted] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  // Portal target is only available in the browser — gate on mount to avoid SSR mismatch.
  useEffect(() => setMounted(true), []);

  // While the modal is open: focus into it, trap Tab, close on Escape, and
  // restore focus to the trigger on close (WCAG 2.1.2 / 2.4.3 focus management).
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;

    const focusable = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((el) => el.offsetParent !== null);

    focusable()[0]?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus.current?.focus();
    };
  }, [open]);

  async function openModal() {
    previousFocus.current = document.activeElement as HTMLElement | null;
    setOpen(true);
    setSent(false);
    setError("");
    // Prefill the email if the user is signed in, so they don't retype it.
    try {
      const { data } = await createClient().auth.getSession();
      const e = data.session?.user?.email;
      if (e) setEmail((prev) => prev || e);
    } catch {
      // not signed in / no session — leave blank
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSending(true);
    setError("");
    try {
      await api.post("/api/support", { name, email, message, website });
      setSent(true);
      setName("");
      setMessage("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <a
        href="#"
        onClick={(e) => {
          e.preventDefault();
          openModal();
        }}
        className={className}
        style={style}
      >
        {label}
      </a>

      {open && mounted && createPortal(
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 100,
            background: "var(--scrim)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px",
          }}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="support-title"
            onClick={(e) => e.stopPropagation()}
            className="card"
            style={{ width: "100%", maxWidth: "440px", padding: "24px" }}
          >
            <div className="flex items-center justify-between mb-1">
              <h3 id="support-title" className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
                Need a hand?
              </h3>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="text-lg leading-none"
                style={{ color: "var(--text-muted)" }}
              >
                ✕
              </button>
            </div>

            {sent ? (
              <div className="py-4 text-center space-y-3">
                <p className="text-3xl">✓</p>
                <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  Thanks — we&apos;ll be in touch soon.
                </p>
                <button onClick={() => setOpen(false)} className="btn btn-secondary">
                  Close
                </button>
              </div>
            ) : (
              <>
                <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
                  Tell us what&apos;s going on and we&apos;ll get back to you by email.
                </p>
                <form onSubmit={handleSubmit} className="space-y-3">
                  <div>
                    <label htmlFor="support-name" className="field-label">Your name</label>
                    <input
                      id="support-name"
                      type="text"
                      required
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="field-input"
                      autoComplete="name"
                    />
                  </div>
                  <div>
                    <label htmlFor="support-email" className="field-label">Your email</label>
                    <input
                      id="support-email"
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="field-input"
                      autoComplete="email"
                    />
                  </div>
                  <div>
                    <label htmlFor="support-message" className="field-label">Message</label>
                    <textarea
                      id="support-message"
                      required
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      className="field-input"
                      rows={4}
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

                  {error && (
                    <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>
                      {error}
                    </p>
                  )}

                  <button type="submit" disabled={sending} className="btn btn-primary w-full">
                    {sending ? "Sending…" : "Send"}
                  </button>
                </form>
              </>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
