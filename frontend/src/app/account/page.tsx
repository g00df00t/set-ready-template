"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";
import AppFooter from "@/components/AppFooter";
import { cleanDisplayName, NAME_MAX } from "@/lib/displayName";
import { cleanBrandName, isBrandColor, readBrand, BRAND_NAME_MAX } from "@/lib/brand";
import { TitleCard } from "@/components/TitleCard";
import { useBeta } from "@/lib/useBeta";
import { JobDefaultsCard } from "@/components/JobDefaultsCard";

// Custom branding stays on staging only (decided 2026-09-30): production has no
// brand-assets bucket, and uploads aren't being offered to other producers. The
// card and its handlers are kept, not deleted, so this is the one line that
// brings it back. Brands already saved in user_metadata still render.
const SHOW_BRANDING = false;

export default function AccountPage() {
  const router = useRouter();
  const { betaJobs, setEnabled: setBetaEnabled } = useBeta();
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [savedName, setSavedName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);
  const [nameError, setNameError] = useState("");
  const [brandName, setBrandName] = useState("");
  const [brandAccent, setBrandAccent] = useState("");
  const [savedBrand, setSavedBrand] = useState("");
  const [savingBrand, setSavingBrand] = useState(false);
  const [brandSaved, setBrandSaved] = useState(false);
  const [brandError, setBrandError] = useState("");
  const [brandImage, setBrandImage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [imageSaved, setImageSaved] = useState(false);
  const [nameInImage, setNameInImage] = useState(false);
  const [brandBg, setBrandBg] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace("/auth/login"); return; }
      setEmail(session.user.email ?? "");
      // `company` is read as a fallback because some accounts were seeded with
      // it before there was any UI for a name — same order the backend uses.
      const meta = session.user.user_metadata ?? {};
      const existing = (meta.full_name as string) || (meta.company as string) || "";
      setName(existing);
      setSavedName(existing);
      const brand = readBrand(meta);
      setBrandName(brand.name ?? "");
      setBrandAccent(brand.accent ?? "");
      setSavedBrand(JSON.stringify([brand.name ?? "", brand.accent ?? ""]));
      setBrandImage(typeof meta.brand_image_url === "string" ? meta.brand_image_url : null);
      setNameInImage(meta.brand_image_has_name === true);
      setBrandBg(typeof meta.brand_background_url === "string" ? meta.brand_background_url : null);
    });
  }, [router]);

  async function handleSaveName() {
    setSavingName(true); setNameError(""); setNameSaved(false);
    try {
      const { error } = await createClient().auth.updateUser({
        data: { full_name: cleanDisplayName(name) ?? "" },
      });
      if (error) throw new Error(error.message);
      setSavedName(name);
      setNameSaved(true);
    } catch (err) {
      setNameError(err instanceof Error ? err.message : "Could not save your name.");
    } finally {
      setSavingName(false);
    }
  }

  async function handleSaveBrand() {
    setSavingBrand(true); setBrandError(""); setBrandSaved(false);
    try {
      const name = cleanBrandName(brandName);
      // An empty field clears the brand rather than storing a blank one, so
      // "remove my branding" is the same gesture as changing it.
      const accent = isBrandColor(brandAccent) ? brandAccent.toLowerCase() : "";
      if (brandAccent && !accent) throw new Error("Use a hex colour like #a8813f."); // color-ok: example of the format, shown as text
      const { error } = await createClient().auth.updateUser({
        data: { brand_name: name ?? "", brand_accent: accent },
      });
      if (error) throw new Error(error.message);
      setSavedBrand(JSON.stringify([name ?? "", accent]));
      setBrandSaved(true);
    } catch (err) {
      setBrandError(err instanceof Error ? err.message : "Could not save your branding.");
    } finally {
      setSavingBrand(false);
    }
  }

  async function handleImage(file: File | null, slot: "card" | "background" = "card") {
    if (!file) return;
    setUploading(true); setBrandError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("slot", slot);
      // Two steps on purpose: the backend re-encodes and stores the file, then
      // the browser records the URL in user_metadata the same way it records
      // the name and colour. Keeping every metadata write on one path means
      // there is one place that decides what a brand is.
      const { url } = await api.upload<{ url: string }>("/api/brand/image", form);
      const field = slot === "card" ? "brand_image_url" : "brand_background_url";
      const { error } = await createClient().auth.updateUser({ data: { [field]: url } });
      if (error) throw new Error(error.message);
      if (slot === "card") setBrandImage(url); else setBrandBg(url);
      setImageSaved(true);
      setTimeout(() => setImageSaved(false), 4000);
    } catch (err) {
      setBrandError(err instanceof Error ? err.message : "Could not upload that image.");
    } finally {
      setUploading(false);
    }
  }

  async function toggleNameInImage(on: boolean) {
    setNameInImage(on);
    try {
      await createClient().auth.updateUser({ data: { brand_image_has_name: on } });
    } catch {
      setNameInImage(!on);
      setBrandError("Could not save that setting.");
    }
  }

  async function handleRemoveImage(slot: "card" | "background" = "card") {
    setUploading(true); setBrandError("");
    try {
      await api.delete(`/api/brand/image?slot=${slot}`);
      const field = slot === "card" ? "brand_image_url" : "brand_background_url";
      const { error } = await createClient().auth.updateUser({ data: { [field]: "" } });
      if (error) throw new Error(error.message);
      if (slot === "card") setBrandImage(null); else setBrandBg(null);
    } catch (err) {
      setBrandError(err instanceof Error ? err.message : "Could not remove that image.");
    } finally {
      setUploading(false);
    }
  }

  const brandDirty = savedBrand !== JSON.stringify([cleanBrandName(brandName) ?? "",
    isBrandColor(brandAccent) ? brandAccent.toLowerCase() : ""]);

  async function handleDelete() {
    setDeleting(true);
    setError("");
    try {
      await api.delete("/api/account");
      const supabase = createClient();
      await supabase.auth.signOut();
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete account.");
      setDeleting(false);
    }
  }

  const armed = confirmText.trim().toUpperCase() === "DELETE";

  async function handleSwitch(enabled: boolean) {
    setSwitching(true); setSwitchError("");
    try {
      await setBetaEnabled(enabled);
    } catch (err) {
      setSwitchError(err instanceof Error ? err.message : "Couldn't switch. Nothing changed — try again.");
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="sticky top-0 z-10 px-6 py-3 flex items-center justify-between"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <Link href="/dashboard" className="text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)", textDecoration: "none" }}>
          SET&gt;READY
        </Link>
        <Link href="/dashboard" className="text-xs" style={{ color: "var(--text-secondary)" }}>
          ← Dashboard
        </Link>
      </header>

      <main className="flex-1 w-full max-w-xl mx-auto px-6 py-10">
        <h1 className="text-xl font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Account</h1>
        <p className="text-sm mb-8" style={{ color: "var(--text-secondary)" }}>{email}</p>

        <div className="card p-6 mb-6">
          <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Your name</h2>
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            The name your crew sees when a call sheet arrives. Use whatever they
            know you by &mdash; if everyone calls you Pat, put Pat.
          </p>

          <label htmlFor="display-name" className="field-label">Name</label>
          <input
            id="display-name"
            type="text"
            value={name}
            maxLength={NAME_MAX}
            placeholder="Pat Kehoe"
            onChange={(e) => { setName(e.target.value); setNameSaved(false); setNameError(""); }}
            className="field-input"
            autoComplete="name"
          />

          {/* The whole point of the card: show the effect, so nobody has to guess
              what this field changes or send a call sheet to find out. */}
          <div
            className="mt-4 p-3 rounded-lg text-sm"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
            aria-live="polite"
          >
            <span style={{ color: "var(--text-muted)" }}>Crew see it as&nbsp;</span>
            {cleanDisplayName(name) ? (
              <span style={{ color: "var(--text-primary)" }}>
                <strong>{cleanDisplayName(name)}</strong> via Set Ready
              </span>
            ) : (
              <>
                <span style={{ color: "var(--text-primary)" }}><strong>Set Ready</strong></span>
                <span style={{ color: "var(--text-muted)" }}>
                  {" "}&mdash; they may not recognise that. Add your name and it becomes yours.
                </span>
              </>
            )}
          </div>

          {nameError && (
            <p role="alert" className="text-xs mt-3" style={{ color: "var(--danger)" }}>{nameError}</p>
          )}

          <div className="flex items-center gap-3 mt-4">
            <button
              onClick={handleSaveName}
              disabled={savingName || name === savedName}
              className="btn btn-primary"
              style={{ cursor: savingName || name === savedName ? "not-allowed" : "pointer", opacity: name === savedName ? 0.55 : 1 }}
            >
              {savingName ? "Saving\u2026" : "Save"}
            </button>
            {nameSaved && (
              <span role="status" className="text-xs" style={{ color: "var(--text-secondary)" }}>
                Saved. Your next call sheet goes out under it.
              </span>
            )}
          </div>
        </div>

        {SHOW_BRANDING && (
        <div className="card p-6 mb-6">
          <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Your company</h2>
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            Your production company&apos;s name and colour. The colour runs through the whole
            workspace, and the name heads the call sheet your crew opens.
          </p>

          <div className="grid gap-4 md:grid-cols-[1fr_170px]">
            <div>
              <label htmlFor="brand-name" className="field-label">Company name</label>
              <input
                id="brand-name"
                type="text"
                value={brandName}
                maxLength={BRAND_NAME_MAX}
                placeholder="Seaworthy"
                onChange={(e) => { setBrandName(e.target.value); setBrandSaved(false); setBrandError(""); }}
                className="field-input"
              />
            </div>
            <div>
              <label htmlFor="brand-accent" className="field-label">Colour</label>
              <div className="flex gap-2">
                <input
                  id="brand-accent"
                  type="text"
                  value={brandAccent}
                  maxLength={7}
                  placeholder="#a8813f" /* color-ok: example of the format, shown as text */
                  onChange={(e) => { setBrandAccent(e.target.value); setBrandSaved(false); setBrandError(""); }}
                  className="field-input font-mono"
                  style={{ minWidth: 0 }}
                />
                {/* The swatch is also the picker: a producer who knows their hex
                    types it, and one who doesn't can go and find it. */}
                <input
                  type="color"
                  aria-label="Pick a colour"
                  value={isBrandColor(brandAccent) ? brandAccent : "#5a5cf0"} /* color-ok: <input type="color"> needs a literal hex, not a CSS variable */
                  onChange={(e) => { setBrandAccent(e.target.value); setBrandSaved(false); setBrandError(""); }}
                  style={{ width: "42px", height: "42px", padding: 0, border: "1px solid var(--border)",
                           borderRadius: "0.5rem", background: "none", cursor: "pointer", flexShrink: 0 }}
                />
              </div>
            </div>
          </div>

          <div className="mt-4">
            <label className="field-label">Title card</label>
            <div className="flex items-center gap-3 flex-wrap">
              <label
                className="btn btn-ghost btn-sm"
                style={{ cursor: uploading ? "not-allowed" : "pointer", opacity: uploading ? 0.6 : 1 }}
              >
                {uploading ? "Uploading\u2026" : brandImage ? "Replace image" : "Upload image"}
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={uploading}
                  onChange={(e) => { handleImage(e.target.files?.[0] ?? null); e.target.value = ""; }}
                  style={{ display: "none" }}
                />
              </label>
              {brandImage && (
                <button onClick={() => handleRemoveImage("card")} disabled={uploading} className="btn btn-ghost btn-sm">
                  Remove
                </button>
              )}
              {/* The artwork saves on upload; the name and colour need the Save
                  button below. Two behaviours on one card is confusing unless
                  each one says which it is — the first version didn't, and the
                  result was an upload that had worked next to a Save button
                  greyed out, which reads as a failure. */}
              <span role="status" className="text-xs" style={{ color: imageSaved ? "var(--success)" : "var(--text-muted)" }}>
                {imageSaved
                  ? "Saved."
                  : brandImage
                    ? "Saved. Uploading again replaces it."
                    : "Fronts the call sheet your crew opens. Saves as soon as it uploads."}
              </span>
            </div>
            {brandImage && (
              // A finished title card already has the company name painted into
              // it. Without this the app sets its own wordmark on top and you
              // get a ghosted double — which is exactly what the first real
              // upload produced.
              <label className="flex items-start gap-2 mt-3 text-sm" style={{ color: "var(--text-secondary)", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={nameInImage}
                  onChange={(e) => toggleNameInImage(e.target.checked)}
                  style={{ marginTop: "3px" }}
                />
                <span>
                  My artwork already includes my company name
                  <span className="block text-xs" style={{ color: "var(--text-muted)" }}>
                    Stops the card setting it a second time on top of the image.
                  </span>
                </span>
              </label>
            )}
          </div>

          {/* Two pictures, because two surfaces want different ones: a title
              card fronts a document and its typography is the point; a masthead
              background sits UNDER a page title, so anything painted into it
              fights the type on top. */}
          <div className="mt-5">
            <label className="field-label">Page background</label>
            <div className="flex items-center gap-3 flex-wrap">
              <label
                className="btn btn-ghost btn-sm"
                style={{ cursor: uploading ? "not-allowed" : "pointer", opacity: uploading ? 0.6 : 1 }}
              >
                {uploading ? "Uploading\u2026" : brandBg ? "Replace image" : "Upload image"}
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={uploading}
                  onChange={(e) => { handleImage(e.target.files?.[0] ?? null, "background"); e.target.value = ""; }}
                  style={{ display: "none" }}
                />
              </label>
              {brandBg && (
                <button onClick={() => handleRemoveImage("background")} disabled={uploading} className="btn btn-ghost btn-sm">
                  Remove
                </button>
              )}
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {brandBg
                  ? "Saved. Sits behind the page title across the app."
                  : "Plain artwork, no lettering \u2014 page titles are set over it."}
              </span>
            </div>
          </div>

          {/* Same reasoning as the name card above: show the thing, so nobody
              has to send a call sheet to find out what they just changed. */}
          <div className="mt-4" aria-live="polite">
            <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
              Crew see this above the call sheet
            </p>
            <TitleCard
              name={cleanBrandName(brandName) ?? "Your company"}
              accent={isBrandColor(brandAccent) ? brandAccent : null}
              image={brandImage}
              nameInImage={nameInImage}
              kind="Call sheet"
              subject="North Shore — Winter Range · Tuesday, February 3"
            />
          </div>

          {brandError && (
            <p role="alert" className="text-xs mt-3" style={{ color: "var(--danger)" }}>{brandError}</p>
          )}

          <div className="flex items-center gap-3 mt-4">
            <button
              onClick={handleSaveBrand}
              disabled={savingBrand || !brandDirty}
              className="btn btn-primary"
              style={{ cursor: savingBrand || !brandDirty ? "not-allowed" : "pointer", opacity: brandDirty ? 1 : 0.55 }}
            >
              {savingBrand ? "Saving\u2026" : "Save name & colour"}
            </button>
            {brandSaved && (
              <span role="status" className="text-xs" style={{ color: "var(--text-secondary)" }}>
                Saved.
              </span>
            )}
          </div>
        </div>
        )}
        {betaJobs !== null && (
          <div className="card p-6 mb-6">
            <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Jobs</h2>
            <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
              {betaJobs
                ? "You're on the Jobs version — the dashboard lists jobs, with Pre-production, Shoot days and Wrap tabs. Switching back returns to today's version, reading the same data."
                : "One place for crew dates, deal memos and every day of a shoot. Try it without losing anything — Switch back returns you here any time."}
            </p>
            <div className="flex items-center gap-3">
              {betaJobs ? (
                <button onClick={() => handleSwitch(false)} disabled={switching} className="btn btn-secondary">
                  {switching ? "Switching back…" : "Switch back"}
                </button>
              ) : (
                <button onClick={() => handleSwitch(true)} disabled={switching} className="btn btn-primary">
                  {switching ? "Switching you over…" : "Try Jobs"}
                </button>
              )}
            </div>
            {switchError && <p role="alert" className="text-xs mt-3" style={{ color: "var(--danger)" }}>{switchError}</p>}
          </div>
        )}
        {betaJobs && <JobDefaultsCard />}

        <div className="card p-6" style={{ borderColor: "var(--danger)" }}>
          <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--danger)" }}>Delete account</h2>
          <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
            This permanently deletes your account and <strong style={{ color: "var(--text-primary)" }}>all</strong> of
            your data — every project, crew member, talent, contact, schedule, location, generated call sheet, and
            your saved rosters. This cannot be undone.
          </p>
          <label htmlFor="confirm-delete" className="field-label">
            Type DELETE to confirm
          </label>
          <input
            id="confirm-delete"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="field-input"
            autoComplete="off"
            aria-describedby={error ? "delete-error" : undefined}
          />
          {error && (
            <p id="delete-error" role="alert" className="text-xs mt-2" style={{ color: "var(--danger)" }}>
              {error}
            </p>
          )}
          <button
            onClick={handleDelete}
            disabled={!armed || deleting}
            className="btn w-full mt-4"
            style={{
              background: armed ? "var(--danger)" : "var(--bg-elevated)",
              color: armed ? "#fff" : "var(--text-muted)",
              border: "none",
              cursor: armed && !deleting ? "pointer" : "not-allowed",
            }}
          >
            {deleting ? "Deleting…" : "Permanently delete my account"}
          </button>
        </div>
      </main>
      <AppFooter />
    </div>
  );
}
