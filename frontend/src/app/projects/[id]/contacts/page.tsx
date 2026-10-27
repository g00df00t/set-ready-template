"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, SLOW_TIMEOUT_MS } from "@/lib/api";
import { fmt, callTimeValue, CALL_TIME_LABELS, timeError } from "@/lib/time";
import { TimeInput } from "@/components/TimeInput";
import { InlineCallTime } from "@/components/InlineCallTime";
import { useToast } from "@/components/Toast";
import { TableSkeleton } from "@/components/Skeleton";

interface Contact {
  id: string;
  organization: string | null;
  name: string;
  role: string | null;
  email: string | null;
  phone: string | null;
  call_time: string | null;
  call_time_note: string | null;
  sort_order: number;
  wants_pdf: boolean;
}

interface RosterEntry {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  organization: string | null;
}

interface EditFields {
  organization: string;
  name: string;
  role: string;
  email: string;
  phone: string;
  call_time: string;
}

interface ImportPreviewMember {
  name: string;
  organization: string;
  role: string;
  email: string;
  phone: string;
  call_time: string;
  match_state?: string;
  match_id?: string | null;
  match_name?: string | null;
  differs?: { field: string; pasted: string | null; existing: string | null }[];
  action?: string;
}

export default function ContactsPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  // Cached by URL — a revisit within the session shows the last-known list
  // instantly instead of blanking to a skeleton again. roster has no writes
  // anywhere on this page, so it stays a plain read.
  const { data: contacts = [], isLoading: contactsLoading, mutate: mutateContacts } =
    useSWR<Contact[]>(`/api/projects/${id}/contacts`, api.get);
  const { data: roster = [] } = useSWR<RosterEntry[]>("/api/roster?type=client", api.get);
  // Whether this project's contacts were empty the moment they first loaded —
  // read once below to decide whether "Continue to Location" appears after
  // adding the first one. Distinct from `contacts.length === 0`, which would
  // also be true (and wrongly show the button) after removing the only one.
  const wasEmpty = useRef<boolean | null>(null);
  const [mode, setMode] = useState<"closed" | "form" | "import">("closed");
  const [organization, setOrganization] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [callTime, setCallTime] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Kept apart from the form-level message so a bad call time highlights the
  // field that produced it, not just the foot of the form.
  const [callTimeError, setCallTimeError] = useState<string | null>(null);
  const [editTimeError, setEditTimeError] = useState<string | null>(null);
  const [rosterSearch, setRosterSearch] = useState("");
  const [showRosterPicker, setShowRosterPicker] = useState(false);
  const rosterRef = useRef<HTMLDivElement>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<EditFields>({ organization: "", name: "", role: "", email: "", phone: "", call_time: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [inlineCallSaving, setInlineCallSaving] = useState<string | null>(null);
  const [wantsPdfSaving, setWantsPdfSaving] = useState<string | null>(null);
  const [importText, setImportText] = useState("");
  const [importParsing, setImportParsing] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportPreviewMember[]>([]);
  const [importPhase, setImportPhase] = useState<"input" | "preview">("input");
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const { show: showToast, node: toastNode } = useToast();

  // First time through this project (no contacts yet, nothing cached): open
  // the add form so the user can start typing immediately instead of clicking
  // "Add contact", and record whether it started empty for wasEmpty above.
  // Guarded to fire once — otherwise removing the last contact later would
  // reopen this form and re-arm the "Continue to Location" button.
  const autoOpenedForm = useRef(false);
  useEffect(() => {
    if (!contactsLoading && !autoOpenedForm.current) {
      autoOpenedForm.current = true;
      wasEmpty.current = contacts.length === 0;
      if (contacts.length === 0) setMode("form");
    }
  }, [contactsLoading, contacts.length]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (rosterRef.current && !rosterRef.current.contains(e.target as Node))
        setShowRosterPicker(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  /* Which Roster entry this form was filled from, held from the moment they
   * pick someone until the row is created. Without it the link is lost between
   * picking and submitting, and the new row would look like a stranger.
   * Editing the fields afterwards doesn't break it — tweaking a role is still
   * the same person. Cleared on submit so the next add starts unlinked. */
  const [rosterId, setRosterId] = useState<string | null>(null);

  function fillFromRoster(entry: RosterEntry) {
    setRosterId(entry.id);
    setName(entry.name); setEmail(entry.email ?? "");
    setPhone(entry.phone ?? ""); setRole(entry.role ?? "");
    setOrganization(entry.organization ?? "");
    setRosterSearch(""); setShowRosterPicker(false);
  }

  // Anyone already on this shoot is filtered out, matching Crew. Without it the
  // picker happily offers a second copy of someone already in the list.
  const contactEmails = new Set(contacts.map((c) => c.email?.toLowerCase()).filter(Boolean));
  const availableRoster = roster.filter((e) => !e.email || !contactEmails.has(e.email.toLowerCase()));
  const rosterMatches = rosterSearch.trim()
    ? availableRoster.filter((e) => [e.name, e.role, e.email, e.organization].some((f) => f?.toLowerCase().includes(rosterSearch.toLowerCase())))
    : availableRoster;

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError(""); setCallTimeError(null);
    try {
      const contact = await api.post<Contact>(`/api/projects/${id}/contacts`, {
        roster_id: rosterId,
        organization: organization || null, name, role: role || null,
        email: email || null, phone: phone || null, call_time: callTime || null,
        sort_order: contacts.length,
      });
      mutateContacts((prev) => [...(prev ?? []), contact], false);
      api.post("/api/roster", {
        name, email: email || null, phone: phone || null, role: role || null,
        organization: organization || null, type: "client",
      }).catch(() => {});
      setOrganization(""); setName(""); setRole(""); setEmail(""); setPhone(""); setCallTime("");
      setRosterId(null);
      showToast(`${contact.name} added`);
    } catch (err) {
      // A refused time belongs on the time field. Anything else has no one
      // field to point at, so it stays where it is.
      const onTimeField = timeError(err);
      setCallTimeError(onTimeField);
      setError(onTimeField ? "" : err instanceof Error ? err.message : "Failed to add contact");
    } finally { setSaving(false); }
  }

  function startEdit(contact: Contact) {
    setEditTimeError(null);
    setEditingId(contact.id);
    setEditFields({ organization: contact.organization ?? "", name: contact.name, role: contact.role ?? "", email: contact.email ?? "", phone: contact.phone ?? "", call_time: callTimeValue(contact) });
  }

  async function handleSave(contactId: string) {
    setEditSaving(true); setEditTimeError(null);
    try {
      const updated = await api.put<Contact>(`/api/projects/${id}/contacts/${contactId}`, {
        organization: editFields.organization || null, name: editFields.name,
        role: editFields.role || null, email: editFields.email || null, phone: editFields.phone || null,
        call_time: editFields.call_time || null,
      });
      mutateContacts((prev) => prev?.map((c) => c.id === contactId ? updated : c), false);
      setEditingId(null);
      showToast("Changes saved");
    } catch (err) {
      // Was a bare console.error, so a refused edit failed in silence — the row
      // stayed open, nothing saved, and nothing said why.
      const onTimeField = timeError(err);
      setEditTimeError(onTimeField);
      if (!onTimeField) showToast(err instanceof Error ? err.message : "Failed to save changes");
    } finally { setEditSaving(false); }
  }

  // On by default for agency and client — they're the ones who file, print, and
  // forward the sheet, which is the whole reason the attachment exists.
  async function handleToggleWantsPdf(contact: Contact) {
    setWantsPdfSaving(contact.id);
    try {
      const updated = await api.put<Contact>(`/api/projects/${id}/contacts/${contact.id}`, {
        wants_pdf: !contact.wants_pdf,
      });
      mutateContacts((prev) => prev?.map((c) => c.id === contact.id ? updated : c), false);
    } catch (err) { console.error(err); }
    finally { setWantsPdfSaving(null); }
  }

  async function handleInlineCallTime(contact: Contact, ct: string) {
    setInlineCallSaving(contact.id);
    try {
      const updated = await api.put<Contact>(`/api/projects/${id}/contacts/${contact.id}`, {
        organization: contact.organization || null, name: contact.name,
        role: contact.role || null, email: contact.email || null, phone: contact.phone || null,
        call_time: ct || null,
      });
      mutateContacts((prev) => prev?.map((c) => c.id === contact.id ? updated : c), false);
    // No catch: the failure belongs on the field the producer typed into, so it
    // propagates to InlineCallTime, which keeps the bad text visible and prints
    // the API's reason underneath it.
    } finally { setInlineCallSaving(null); }
  }

  async function handleRemove(contactId: string) {
    await api.delete(`/api/projects/${id}/contacts/${contactId}`);
    mutateContacts((prev) => prev?.filter((c) => c.id !== contactId), false);
  }

  function updatePreviewMember(idx: number, field: keyof ImportPreviewMember, value: string) {
    setImportPreview((prev) => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m));
  }

  async function handleParse() {
    if (!importText.trim()) return;
    setImportParsing(true);
    setImportError("");
    try {
      const result = await api.post<{ members: ImportPreviewMember[] }>(
        `/api/projects/${id}/contacts/import/parse`,
        { text: importText },
        { timeoutMs: SLOW_TIMEOUT_MS }
      );
      setImportPreview(result.members.map((m) => ({
        name: m.name || "",
        organization: m.organization || "",
        role: m.role || "",
        email: m.email || "",
        phone: m.phone || "",
        call_time: m.call_time || "",
        // The verdict the API just computed. An explicit shape keeps UI-only
        // flags out of the request body, but it silently drops anything the API
        // starts sending — which is exactly how the crew version shipped broken.
        match_state: m.match_state,
        match_id: m.match_id ?? null,
        match_name: m.match_name ?? null,
        differs: m.differs ?? [],
        action: m.action ?? "add",
      })));
      setImportPhase("preview");
    } catch {
      setImportError("Could not parse the pasted text. Check that it contains names and try again.");
    } finally {
      setImportParsing(false);
    }
  }

  /* What a pasted row already is. Same contract and wording as the crew import
   * — see app/projects/[id]/crew/page.tsx. The tool proposes; the producer
   * decides, and confirm obeys whatever they chose. */
  function importStatusCell(member: ImportPreviewMember, idx: number) {
    const state = member.match_state ?? "new";
    const differs = member.differs ?? [];
    const LABELS: Record<string, { text: string; colour: string }> = {
      on_project: { text: "Already on this shoot", colour: "var(--accent-hover)" },
      in_roster:  { text: "In your Roster",        colour: "var(--accent-hover)" },
      ambiguous:  { text: "Possible match",        colour: "var(--text-muted)" },
      new:        { text: "New",                   colour: "var(--text-muted)" },
    };
    const { text, colour } = LABELS[state] ?? LABELS.new;
    const filedAs = member.match_name
      && member.match_name.trim().toLowerCase() !== member.name.trim().toLowerCase();
    return (
      <div className="space-y-1">
        <div className="text-xs" style={{ color: colour }}>
          {text}
          {filedAs && <span style={{ color: "var(--text-muted)" }}> as &ldquo;{member.match_name}&rdquo;</span>}
        </div>
        {differs.length > 0 && (
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            {differs.map((d) => d.field).join(", ")} differ{differs.length === 1 ? "s" : ""}
          </div>
        )}
        {state !== "new" && (
          <select
            aria-label={`What to do with ${member.name}`}
            value={member.action ?? "add"}
            onChange={(e) => updatePreviewMember(idx, "action", e.target.value)}
            className="field-input py-1 text-xs"
          >
            <option value="add">{state === "on_project" ? "Add anyway" : "Add"}</option>
            <option value="skip">Skip</option>
            {state === "on_project" && differs.length > 0 && (
              <option value="update">Update the one here</option>
            )}
          </select>
        )}
      </div>
    );
  }

  async function handleImportConfirm() {
    const valid = importPreview.filter((m) => m.name.trim()).map((m) => ({
      ...m,
      // The verdict travels back so confirm can link without re-deciding.
      action: m.action ?? "add",
    }));
    if (!valid.length) return;
    setImportBusy(true);
    try {
      const created = await api.post<Contact[]>(
        `/api/projects/${id}/contacts/import/confirm`,
        { members: valid }
      );
      mutateContacts((prev) => [...(prev ?? []), ...created], false);
      setMode("closed");
      setImportText("");
      setImportPreview([]);
      setImportPhase("input");
      showToast(`${created.length} contact${created.length === 1 ? "" : "s"} imported`);
    } catch {
      setImportError("Import failed. Please try again.");
    } finally {
      setImportBusy(false);
    }
  }

  function close() {
    setMode("closed");
    setError("");
    setImportText("");
    setImportPreview([]);
    setImportPhase("input");
    setImportError("");
  }

  const validImportCount = importPreview.filter((m) => m.name.trim()).length;

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10">
      {toastNode}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Agency & Client</h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Email and phone are used for delivery only. Call time appears on the call sheet — agency &amp; client often arrive later than crew.</p>
        </div>
        <div className="flex gap-2 shrink-0">
          {mode === "closed" ? (
            <>
              {contacts.length > 0 && wasEmpty.current && (
                <button onClick={() => router.push(`/projects/${id}/location`)} className="btn btn-ghost">
                  Continue to Location →
                </button>
              )}
              <button onClick={() => { setMode("import"); setImportPhase("input"); }} className="btn btn-secondary">
                Quick Import
              </button>
              <button onClick={() => setMode("form")} className="btn btn-primary">Add contact</button>
            </>
          ) : mode === "form" ? (
            <>
              <button onClick={() => { setMode("import"); setImportPhase("input"); }} className="btn btn-secondary">
                Quick Import
              </button>
              <button onClick={close} className="btn btn-ghost">Done</button>
            </>
          ) : (
            <button onClick={close} className="btn btn-ghost">Done</button>
          )}
        </div>
      </div>

      {/* Add form */}
      {mode === "form" && (
        <div className="card p-5 mb-6 space-y-4">
          {availableRoster.length > 0 && (
            <div ref={rosterRef} className="relative">
              <label className="field-label">From roster</label>
              <input
                aria-label="Search saved contacts"
                value={rosterSearch}
                onChange={(e) => { setRosterSearch(e.target.value); setShowRosterPicker(true); }}
                onFocus={() => setShowRosterPicker(true)}
                placeholder="Search saved contacts…"
                className="field-input"
              />
              {showRosterPicker && rosterMatches.length > 0 && (
                <div className="absolute z-10 mt-1 w-full card shadow-xl max-h-52 overflow-y-auto" style={{ boxShadow: "0 20px 40px var(--shadow-color)" }}>
                  {rosterMatches.map((entry) => (
                    <button key={entry.id} type="button" onClick={() => fillFromRoster(entry)}
                      className="w-full text-left px-4 py-3 transition-colors"
                      style={{ borderBottom: "1px solid var(--border)" }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-elevated)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{entry.name}</span>
                      {entry.role && <span className="text-xs ml-2" style={{ color: "var(--text-secondary)" }}>{entry.role}</span>}
                      {entry.email && <span className="text-xs block mt-0.5" style={{ color: "var(--text-muted)" }}>{entry.email}</span>}
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-4" style={{ borderBottom: "1px solid var(--border)" }} />
            </div>
          )}
          <form onSubmit={handleAdd} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div><label className="field-label">Organization</label><input aria-label="Organization" value={organization} onChange={(e) => setOrganization(e.target.value)} placeholder="Creative Agency, Inc." className="field-input" /></div>
              <div><label className="field-label">Name</label><input required aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} className="field-input" /></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><label className="field-label">Role</label><input aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Creative Director" className="field-input" /></div>
              <div><label className="field-label">Phone</label><input aria-label="Phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(206) 555-0100" className="field-input" /></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div><label className="field-label">Email — for call sheet delivery</label><input aria-label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="client@agency.com" className="field-input" /></div>
              <div><label className="field-label">Call time <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(shown on call sheet)</span></label><TimeInput value={callTime} onChange={(v) => { setCallTime(v); setCallTimeError(null); }} error={callTimeError} /></div>
            </div>
            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button type="submit" disabled={saving} className="btn btn-primary">{saving ? "Adding…" : "Add"}</button>
          </form>
        </div>
      )}

      {/* Paste import — input */}
      {mode === "import" && importPhase === "input" && (
        <div className="card p-5 mb-6 space-y-4">
          <div>
            <label className="field-label">Paste contact data</label>
            <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
              Paste rows from a spreadsheet or contact list — names, organizations, roles, emails, and phone numbers will be extracted automatically.
            </p>
            <textarea
              aria-label="Paste contact data"
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              rows={8}
              placeholder={"Jane Smith\tCreative Director\tSome Agency\tjane@agency.com\t310-555-1234\nBob Jones\tArt Buyer\tBrand Co\tbob@brand.com\t310-555-5678"}
              className="field-input font-mono text-sm"
              style={{ resize: "vertical" }}
              autoFocus
            />
          </div>
          {importError && <p className="text-xs" style={{ color: "var(--danger)" }}>{importError}</p>}
          <button
            onClick={handleParse}
            disabled={!importText.trim() || importParsing}
            className="btn btn-primary"
          >
            {importParsing ? "Importing…" : "Import"}
          </button>
        </div>
      )}

      {/* Paste import — preview */}
      {mode === "import" && importPhase === "preview" && (
        <div className="card mb-6">
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: "1px solid var(--border)" }}>
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              {importPreview.length} {importPreview.length === 1 ? "person" : "people"} found — review and edit before importing
            </p>
            <button onClick={() => setImportPhase("input")} className="btn btn-ghost btn-sm">← Back</button>
          </div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>Name</th><th>Organization</th><th>Role</th><th>Email</th><th>Phone</th><th>Call time</th><th>Already known?</th><th /></tr>
              </thead>
              <tbody>
                {importPreview.map((member, idx) => (
                  <tr key={idx}>
                    <td><input aria-label="Name" value={member.name} onChange={(e) => updatePreviewMember(idx, "name", e.target.value)} className="field-input" /></td>
                    <td><input aria-label="Organization" value={member.organization} onChange={(e) => updatePreviewMember(idx, "organization", e.target.value)} className="field-input" /></td>
                    <td><input aria-label="Role" value={member.role} onChange={(e) => updatePreviewMember(idx, "role", e.target.value)} className="field-input" /></td>
                    <td><input aria-label="Email" type="email" value={member.email} onChange={(e) => updatePreviewMember(idx, "email", e.target.value)} className="field-input" /></td>
                    <td><input aria-label="Phone" type="tel" value={member.phone} onChange={(e) => updatePreviewMember(idx, "phone", e.target.value)} className="field-input" /></td>
                    <td><input aria-label="Call time" value={member.call_time} onChange={(e) => updatePreviewMember(idx, "call_time", e.target.value)} placeholder="8:00 AM" className="field-input" /></td>
                    <td style={{ minWidth: "13rem" }}>{importStatusCell(member, idx)}</td>
                    <td>
                      <button
                        onClick={() => setImportPreview((prev) => prev.filter((_, i) => i !== idx))}
                        className="btn btn-ghost btn-sm"
                        style={{ color: "var(--danger)" }}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-4 flex items-center gap-3" style={{ borderTop: "1px solid var(--border)" }}>
            <button
              onClick={handleImportConfirm}
              disabled={importBusy || validImportCount === 0}
              className="btn btn-primary"
            >
              {importBusy ? "Importing…" : `Import ${validImportCount} ${validImportCount === 1 ? "person" : "people"}`}
            </button>
            {importError && <p className="text-xs" style={{ color: "var(--danger)" }}>{importError}</p>}
          </div>
        </div>
      )}

      {contactsLoading ? (
        <TableSkeleton columns={6} />
      ) : contacts.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No contacts yet.</p>
      ) : (
        <div className="space-y-2">
          {contacts.map((contact) =>
            editingId === contact.id ? (
              <div key={contact.id} className="card p-5 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="field-label">Organization</label><input aria-label="Organization" value={editFields.organization} onChange={(e) => setEditFields((f) => ({ ...f, organization: e.target.value }))} className="field-input" /></div>
                  <div><label className="field-label">Name</label><input aria-label="Name" value={editFields.name} onChange={(e) => setEditFields((f) => ({ ...f, name: e.target.value }))} className="field-input" /></div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="field-label">Role</label><input aria-label="Role" value={editFields.role} onChange={(e) => setEditFields((f) => ({ ...f, role: e.target.value }))} className="field-input" /></div>
                  <div><label className="field-label">Phone</label><input aria-label="Phone" value={editFields.phone} onChange={(e) => setEditFields((f) => ({ ...f, phone: e.target.value }))} className="field-input" /></div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="field-label">Email</label><input aria-label="Email" value={editFields.email} onChange={(e) => setEditFields((f) => ({ ...f, email: e.target.value }))} className="field-input" /></div>
                  <div><label className="field-label">Call time</label><TimeInput value={editFields.call_time} onChange={(v) => { setEditFields((f) => ({ ...f, call_time: v })); setEditTimeError(null); }} error={editTimeError} /></div>
                </div>
                <div className="flex gap-3">
                  <button onClick={() => handleSave(contact.id)} disabled={editSaving} className="btn btn-primary btn-sm">{editSaving ? "Saving…" : "Save"}</button>
                  <button onClick={() => setEditingId(null)} className="btn btn-ghost btn-sm">Cancel</button>
                </div>
              </div>
            ) : (
              <div key={contact.id} className="card px-5 py-4">
                <div className="flex items-start justify-between">
                  <div>
                    {contact.organization && <p className="text-xs mb-0.5" style={{ color: "var(--text-muted)" }}>{contact.organization}</p>}
                    <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{contact.name}</p>
                    {contact.role && <p className="text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>{contact.role}</p>}
                    <div className="flex gap-4 mt-1">
                      {contact.phone && <p className="text-xs" style={{ color: "var(--text-muted)" }}>{contact.phone}</p>}
                      {contact.email && <p className="text-xs" style={{ color: "var(--text-muted)" }}>{contact.email}</p>}
                    </div>
                  </div>
                  <div className="flex items-start gap-3 ml-4 shrink-0">
                    <div className="flex flex-col items-end">
                      <label className="text-[10px] uppercase tracking-wide mb-0.5" style={{ color: "var(--text-muted)" }}>Call time</label>
                      <InlineCallTime
                        initial={callTimeValue(contact)}
                        saving={inlineCallSaving === contact.id}
                        onSave={(v) => handleInlineCallTime(contact, v)}
                        floatAlign="right"
                      />
                    </div>
                    <div className="flex flex-col items-end">
                      <label className="text-[10px] uppercase tracking-wide mb-0.5" style={{ color: "var(--text-muted)" }}>PDF</label>
                      <button
                        onClick={() => handleToggleWantsPdf(contact)}
                        disabled={wantsPdfSaving === contact.id}
                        aria-pressed={contact.wants_pdf}
                        aria-label={`${contact.wants_pdf ? "Stop attaching" : "Attach"} a PDF copy for ${contact.name}`}
                        title={
                          contact.wants_pdf
                            ? "A PDF copy is attached to their email"
                            : "No PDF attached — they still get the sheet in the email"
                        }
                        className="btn btn-ghost btn-sm whitespace-nowrap"
                        style={{ color: contact.wants_pdf ? "var(--accent-hover)" : "var(--text-muted)" }}
                      >
                        {wantsPdfSaving === contact.id ? "…" : contact.wants_pdf ? "Attached" : "None"}
                      </button>
                    </div>
                    <button onClick={() => startEdit(contact)} className="btn btn-ghost btn-sm mt-4">Edit</button>
                    <button onClick={() => handleRemove(contact.id)} className="btn btn-danger btn-sm mt-4">Remove</button>
                  </div>
                </div>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
