"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, SLOW_TIMEOUT_MS } from "@/lib/api";
import { fmt, callTimeValue, CALL_TIME_LABELS, timeError } from "@/lib/time";
import { useToast } from "@/components/Toast";
import { TimeInput } from "@/components/TimeInput";
import { InlineCallTime } from "@/components/InlineCallTime";
import { TableSkeleton } from "@/components/Skeleton";

interface TalentMember {
  id: string;
  role: string | null;
  name: string;
  phone: string | null;
  email: string | null;
  call_time: string | null;
  call_time_note: string | null;
  location_assignment: string | null;
  hide_contact: boolean;
  sort_order: number;
}

interface CompanyMove {
  id: string;
  label: string | null;
  location_name: string | null;
  sort_order: number;
}

interface RosterEntry {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
}

interface EditFields {
  role: string;
  name: string;
  phone: string;
  email: string;
  call_time: string;
  location_assignment: string;
}

interface ImportPreviewMember {
  name: string;
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

function LocationSelect({ value, onChange, moves }: {
  value: string;
  onChange: (v: string) => void;
  moves: CompanyMove[];
}) {
  function moveLabel(move: CompanyMove, idx: number) {
    return move.label || move.location_name || `Company Move ${idx + 1}`;
  }
  return (
    <select aria-label="Location" value={value} onChange={(e) => onChange(e.target.value)} className="field-input">
      <option value="">— No assignment —</option>
      <option value="primary">Primary Location</option>
      {moves.map((m, idx) => (
        <option key={m.id} value={m.id}>{moveLabel(m, idx)}</option>
      ))}
    </select>
  );
}

export default function TalentPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  // Cached by URL — a revisit within the session shows the last-known list
  // instantly instead of blanking to a skeleton again. moves and roster have
  // no writes anywhere on this page, so they stay plain reads; only talent
  // needs `mutate` for the API responses that follow.
  const { data: talent = [], isLoading: talentLoading, mutate: mutateTalent } =
    useSWR<TalentMember[]>(`/api/projects/${id}/talent`, api.get);
  const { data: moves = [] } = useSWR<CompanyMove[]>(`/api/projects/${id}/company-moves`, api.get);
  const { data: roster = [] } = useSWR<RosterEntry[]>("/api/roster?type=talent", api.get);
  const [mode, setMode] = useState<"closed" | "form" | "import">("closed");
  const [role, setRole] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [callTime, setCallTime] = useState("");
  const [locationAssignment, setLocationAssignment] = useState("");
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
  const [editFields, setEditFields] = useState<EditFields>({ role: "", name: "", phone: "", email: "", call_time: "", location_assignment: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const [inlineCallSaving, setInlineCallSaving] = useState<string | null>(null);
  const [hideContactSaving, setHideContactSaving] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [importText, setImportText] = useState("");
  const [importParsing, setImportParsing] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportPreviewMember[]>([]);
  const [importPhase, setImportPhase] = useState<"input" | "preview">("input");
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const { show: showToast, node: toastNode } = useToast();

  // First time through this project (no talent yet, nothing cached): open the
  // add form so the user can start typing immediately instead of clicking
  // "Add talent". Guarded to fire once — otherwise removing the last talent
  // member later would reopen this form every time the list became empty.
  const autoOpenedForm = useRef(false);
  useEffect(() => {
    if (!talentLoading && !autoOpenedForm.current) {
      autoOpenedForm.current = true;
      if (talent.length === 0) setMode("form");
    }
  }, [talentLoading, talent.length]);

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
    setRosterSearch(""); setShowRosterPicker(false);
  }

  function locationLabel(assignment: string | null) {
    if (!assignment) return "—";
    if (assignment === "primary") return "Primary Location";
    const idx = moves.findIndex((m) => m.id === assignment);
    if (idx === -1) return "—";
    const m = moves[idx];
    return m.label || m.location_name || `Company Move ${idx + 1}`;
  }

  // Anyone already on this shoot is filtered out, matching Crew. Without it the
  // picker happily offers a second copy of someone already in the list.
  const talentEmails = new Set(talent.map((t) => t.email?.toLowerCase()).filter(Boolean));
  const availableRoster = roster.filter((e) => !e.email || !talentEmails.has(e.email.toLowerCase()));
  const rosterMatches = rosterSearch.trim()
    ? availableRoster.filter((e) => [e.name, e.role, e.email].some((f) => f?.toLowerCase().includes(rosterSearch.toLowerCase())))
    : availableRoster;

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError(""); setCallTimeError(null);
    try {
      const member = await api.post<TalentMember>(`/api/projects/${id}/talent`, {
        roster_id: rosterId,
        role: role || null, name, phone: phone || null, email: email || null,
        call_time: callTime || null,
        location_assignment: locationAssignment || null,
      });
      mutateTalent((prev) => [...(prev ?? []), member], false);
      api.post("/api/roster", { name, email: email || null, phone: phone || null, role: role || null, type: "talent" }).catch(() => {});
      showToast(`${member.name} added to talent`);
      setRole(""); setName(""); setPhone(""); setEmail(""); setCallTime(""); setLocationAssignment("");
      setRosterId(null);
    } catch (err) {
      // A refused time belongs on the time field. Anything else has no one
      // field to point at, so it stays where it is.
      const onTimeField = timeError(err);
      setCallTimeError(onTimeField);
      setError(onTimeField ? "" : err instanceof Error ? err.message : "Failed to add talent");
    } finally { setSaving(false); }
  }

  function startEdit(t: TalentMember) {
    setEditTimeError(null);
    setEditingId(t.id);
    setEditFields({
      role: t.role ?? "", name: t.name, phone: t.phone ?? "",
      email: t.email ?? "", call_time: callTimeValue(t),
      location_assignment: t.location_assignment ?? "",
    });
  }

  async function handleSave(talentId: string) {
    setEditSaving(true); setEditError(""); setEditTimeError(null);
    try {
      const updated = await api.put<TalentMember>(`/api/projects/${id}/talent/${talentId}`, {
        role: editFields.role || null, name: editFields.name,
        phone: editFields.phone || null, email: editFields.email || null,
        call_time: editFields.call_time || null,
        location_assignment: editFields.location_assignment || null,
      });
      mutateTalent((prev) => prev?.map((t) => t.id === talentId ? updated : t), false);
      setEditingId(null);
      showToast("Changes saved");
    } catch (err) {
      // A refused time belongs on the time field. Anything else has no one
      // field to point at, so it stays where it is.
      const onTimeField = timeError(err);
      setEditTimeError(onTimeField);
      setEditError(onTimeField ? "" : err instanceof Error ? err.message : "Failed to save");
    } finally { setEditSaving(false); }
  }

  async function handleInlineCallTime(t: TalentMember, ct: string) {
    setInlineCallSaving(t.id);
    try {
      const updated = await api.put<TalentMember>(`/api/projects/${id}/talent/${t.id}`, {
        role: t.role || null, name: t.name, phone: t.phone || null, email: t.email || null,
        call_time: ct || null, location_assignment: t.location_assignment || null,
      });
      mutateTalent((prev) => prev?.map((x) => x.id === t.id ? updated : x), false);
    // No catch: the failure belongs on the field the producer typed into, so it
    // propagates to InlineCallTime, which keeps the bad text visible and prints
    // the API's reason underneath it.
    } finally { setInlineCallSaving(null); }
  }

  // Talent contact details default to hidden — the agency fields those calls —
  // but a producer can expose them per person. Delivery is unaffected.
  async function handleToggleHideContact(t: TalentMember) {
    setHideContactSaving(t.id);
    try {
      const updated = await api.put<TalentMember>(`/api/projects/${id}/talent/${t.id}`, {
        hide_contact: !t.hide_contact,
      });
      mutateTalent((prev) => prev?.map((x) => x.id === t.id ? updated : x), false);
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to update contact visibility"); }
    finally { setHideContactSaving(null); }
  }

  async function handleRemove(talentId: string) {
    if (confirmRemove !== talentId) { setConfirmRemove(talentId); return; }
    setConfirmRemove(null);
    await api.delete(`/api/projects/${id}/talent/${talentId}`);
    mutateTalent((prev) => prev?.filter((t) => t.id !== talentId), false);
  }

  // Persist the visible order as contiguous sort_order values — the same shape
  // crew uses, so the sheet reads both sections from one rule.
  async function persistOrder(next: TalentMember[]) {
    const withOrders = next.map((t, i) => ({ ...t, sort_order: i }));
    mutateTalent(withOrders, false);
    try {
      await Promise.all(withOrders.map((t) => api.put(`/api/projects/${id}/talent/${t.id}`, { sort_order: t.sort_order })));
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to save new order"); }
  }

  async function handleDrop(toIdx: number) {
    if (dragIndex === null || dragIndex === toIdx) { setDragIndex(null); setDragOverIndex(null); return; }
    const reordered = [...talent];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(toIdx, 0, moved);
    setDragIndex(null); setDragOverIndex(null);
    await persistOrder(reordered);
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
        `/api/projects/${id}/talent/import/parse`,
        { text: importText },
        { timeoutMs: SLOW_TIMEOUT_MS }
      );
      setImportPreview(result.members.map((m) => ({
        name: m.name || "",
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
      const created = await api.post<TalentMember[]>(
        `/api/projects/${id}/talent/import/confirm`,
        { members: valid }
      );
      mutateTalent((prev) => [...(prev ?? []), ...created], false);
      setMode("closed");
      setImportText("");
      setImportPreview([]);
      setImportPhase("input");
      showToast(`${created.length} talent member${created.length === 1 ? "" : "s"} imported`);
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

  const showLocationColumn = moves.length > 0;
  const validImportCount = importPreview.filter((m) => m.name.trim()).length;

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10">
      {toastNode}
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Talent</h2>
        <div className="flex items-center gap-2">
          {talent.length > 0 && mode === "closed" && (
            <button onClick={() => router.push(`/projects/${id}/contacts`)} className="btn btn-ghost">
              Continue to Agency &amp; Client →
            </button>
          )}
          {mode === "closed" ? (
            <>
              <button onClick={() => { setMode("import"); setImportPhase("input"); }} className="btn btn-secondary">
                Quick Import
              </button>
              <button onClick={() => setMode("form")} className="btn btn-primary">Add talent</button>
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
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="field-label">Name</label><input required aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} className="field-input" /></div>
              <div><label className="field-label">Role</label><input aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Lead Talent" className="field-input" /></div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="field-label">Phone</label><input aria-label="Phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(555) 555-5555" className="field-input" /></div>
              <div><label className="field-label">Email</label><input aria-label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="field-input" /></div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="field-label">Call time</label><TimeInput value={callTime} onChange={(v) => { setCallTime(v); setCallTimeError(null); }} error={callTimeError} /></div>
              {showLocationColumn && (
                <div>
                  <label className="field-label">Location</label>
                  <LocationSelect value={locationAssignment} onChange={setLocationAssignment} moves={moves} />
                </div>
              )}
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
            <label className="field-label">Paste talent data</label>
            <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
              Paste rows from a spreadsheet or contact list — names, roles, emails, and phone numbers will be extracted automatically.
            </p>
            <textarea
              aria-label="Paste talent data"
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              rows={8}
              placeholder={"Jane Smith\tLead Talent\tjane@agency.com\t310-555-1234\nBob Jones\tPrincipal\tbob@agency.com\t310-555-5678"}
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
                <tr><th>Name</th><th>Role</th><th>Email</th><th>Phone</th><th>Call time</th><th>Already known?</th><th /></tr>
              </thead>
              <tbody>
                {importPreview.map((member, idx) => (
                  <tr key={idx}>
                    <td><input aria-label="Name" value={member.name} onChange={(e) => updatePreviewMember(idx, "name", e.target.value)} className="field-input" /></td>
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

      {talentLoading ? (
        <TableSkeleton columns={6} />
      ) : talent.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No talent added yet.</p>
      ) : (
        <>
        {talent.length > 1 && (
          <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
            Drag <span className="select-none">⠿</span> to set the order talent appears on the call sheet.
          </p>
        )}
        <div className="card overflow-x-auto">
          {/* Same reason as the crew table: width:100% means the wrapper can
              never scroll, so a narrow window clips the last column instead. */}
          <table className="data-table" style={{ minWidth: "56rem" }}>
            <thead>
              <tr>
                <th /><th>Name</th><th>Role</th><th>Phone</th><th>Email</th><th>Call time</th>
                {showLocationColumn && <th>Location</th>}
                <th>On sheet</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {talent.map((t, rowIdx) =>
                editingId === t.id ? (
                  <tr key={t.id}>
                    {/* Keep the handle column aligned while editing. */}
                    <td />
                    <td><input aria-label="Name" value={editFields.name} onChange={(e) => setEditFields((f) => ({ ...f, name: e.target.value }))} className="field-input" /></td>
                    <td><input aria-label="Role" value={editFields.role} onChange={(e) => setEditFields((f) => ({ ...f, role: e.target.value }))} className="field-input" /></td>
                    <td><input aria-label="Phone" type="tel" value={editFields.phone} onChange={(e) => setEditFields((f) => ({ ...f, phone: e.target.value }))} className="field-input" /></td>
                    <td><input aria-label="Email" type="email" value={editFields.email} onChange={(e) => setEditFields((f) => ({ ...f, email: e.target.value }))} className="field-input" /></td>
                    <td>
                      <span style={{ position: "relative", display: "inline-block" }}>
                        <TimeInput
                          value={editFields.call_time}
                          onChange={(v) => { setEditFields((f) => ({ ...f, call_time: v })); setEditTimeError(null); }}
                          error={editTimeError}
                          floatError="left"
                          style={{ width: "7.5rem" }}
                        />
                      </span>
                    </td>
                    {showLocationColumn && (
                      <td><LocationSelect value={editFields.location_assignment} onChange={(v) => setEditFields((f) => ({ ...f, location_assignment: v }))} moves={moves} /></td>
                    )}
                    {/* Contact visibility saves on its own; keep the column aligned while editing. */}
                    <td />
                    <td className="text-right whitespace-nowrap">
                      {editError && <span className="text-xs mr-2" style={{ color: "var(--danger)" }}>{editError}</span>}
                      <button onClick={() => handleSave(t.id)} disabled={editSaving} className="btn btn-ghost btn-sm mr-1">{editSaving ? "Saving…" : "Save"}</button>
                      <button onClick={() => setEditingId(null)} className="btn btn-ghost btn-sm">Cancel</button>
                    </td>
                  </tr>
                ) : (
                  <tr
                    key={t.id}
                    onDragOver={(e) => { e.preventDefault(); if (dragOverIndex !== rowIdx) setDragOverIndex(rowIdx); }}
                    onDrop={() => handleDrop(rowIdx)}
                    style={{
                      opacity: dragIndex === rowIdx ? 0.4 : 1,
                      background: dragOverIndex === rowIdx && dragIndex !== rowIdx ? "var(--bg-surface)" : undefined,
                    }}
                  >
                    <td>
                      <span
                        draggable
                        onDragStart={() => setDragIndex(rowIdx)}
                        onDragEnd={() => { setDragIndex(null); setDragOverIndex(null); }}
                        className="cursor-grab select-none text-base"
                        style={{ color: "var(--text-muted)" }}
                        title="Drag to reorder"
                        aria-label={`Reorder ${t.name}`}
                      >
                        ⠿
                      </span>
                    </td>
                    <td className="font-medium" style={{ color: "var(--text-primary)" }}>{t.name}</td>
                    <td style={{ color: "var(--text-secondary)" }}>{t.role ?? "—"}</td>
                    <td style={{ color: "var(--text-secondary)" }}>{t.phone ?? "—"}</td>
                    <td style={{ color: "var(--text-secondary)" }}>{t.email ?? "—"}</td>
                    <td><InlineCallTime initial={callTimeValue(t)} saving={inlineCallSaving === t.id} onSave={(v) => handleInlineCallTime(t, v)} /></td>
                    {showLocationColumn && (
                      <td style={{ color: "var(--text-secondary)" }}>{locationLabel(t.location_assignment)}</td>
                    )}
                    <td>
                      <button
                        onClick={() => handleToggleHideContact(t)}
                        disabled={hideContactSaving === t.id}
                        aria-pressed={t.hide_contact}
                        aria-label={`${t.hide_contact ? "Show" : "Hide"} phone and email for ${t.name} on the call sheet`}
                        title={
                          t.hide_contact
                            ? "Phone and email are hidden on the call sheet. They still receive it."
                            : "Phone and email appear on the call sheet"
                        }
                        className="btn btn-ghost btn-sm whitespace-nowrap"
                        style={{ color: t.hide_contact ? "var(--accent-hover)" : "var(--text-muted)" }}
                      >
                        {hideContactSaving === t.id ? "…" : t.hide_contact ? "Hidden" : "Shown"}
                      </button>
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <button onClick={() => startEdit(t)} className="btn btn-ghost btn-sm mr-1">Edit</button>
                      <button
                        onClick={() => handleRemove(t.id)}
                        onMouseLeave={() => { if (confirmRemove === t.id) setConfirmRemove(null); }}
                        className={confirmRemove === t.id ? "btn btn-danger btn-sm" : "btn btn-ghost btn-sm"}
                        style={confirmRemove !== t.id ? { color: "var(--danger)" } : {}}
                      >
                        {confirmRemove === t.id ? "Sure?" : "Remove"}
                      </button>
                    </td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        </div>
        </>
      )}
    </div>
  );
}
