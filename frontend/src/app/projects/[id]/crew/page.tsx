"use client";

import { useEffect, useMemo, useState, useRef } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { api, SLOW_TIMEOUT_MS } from "@/lib/api";
import { fmt, addMinutes, callTimeValue, CALL_TIME_LABELS, timeError } from "@/lib/time";
import { TimeInput } from "@/components/TimeInput";
import { InlineCallTime } from "@/components/InlineCallTime";
import { useToast } from "@/components/Toast";
import { TableSkeleton } from "@/components/Skeleton";
import { useBeta } from "@/lib/useBeta";

const DEPARTMENTS = [
  "General Crew", "Above the Line",
  "Camera Department", "Grip & Electric", "Sound Department", "Art Department", "Production",
  "Wardrobe/Costume", "Hair & Makeup", "Transportation", "Catering & Craft Services",
];

// A department that isn't one of the presets still has to appear in every
// dropdown, or the select has no option matching the stored value and renders
// blank — the row reads as "no department" while the grouping header above it
// says otherwise, and the producer can silently overwrite it by touching the
// field. Two ways in: someone typed one ("Locations"), or Quick Import parsed a
// name that isn't spelled like a preset ("Wardrobe" vs "Wardrobe/Costume").
function withExtra(options: string[], value: string | null | undefined): string[] {
  return value && value !== "__custom__" && !options.includes(value) ? [...options, value] : options;
}

interface CrewMember {
  id: string;
  hire_id?: string | null;
  name: string;
  email: string;
  role: string;
  phone: string | null;
  call_time: string | null;
  call_time_note: string | null;
  department: string | null;
  sort_order: number;
  confirmed_at: string | null;
  hide_contact: boolean;
  wants_pdf: boolean;
}

interface RosterEntry {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  department: string | null;
}

interface Hire {
  id: string;
  // Carried through to the crew row, same as "Add from roster" — so a
  // correction made on this day still reaches the Master Roster entry the
  // hire itself is already linked to.
  roster_id: string | null;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  department: string | null;
  // From the Pre-production sheet's own Dates block — shown so a producer can
  // see whether this person's dates cover the day before adding them; nothing
  // here decides that for them (docs/job-layer-plan.md §6).
  dates_text: string;
  // Their actual dates by day type (the crew's, or their own) — what says
  // whether they're working this day.
  effective_dates?: Record<string, [string, string][]>;
  days: { id: string; name: string; shoot_date: string | null }[];
}

interface ProjectSlim {
  job_id: string | null;
  shoot_date: string | null;
}

interface EditFields {
  name: string;
  email: string;
  role: string;
  phone: string;
  call_time: string;
  department: string;
}

interface ImportPreviewMember {
  name: string;
  role: string;
  email: string;
  phone: string;
  department: string;
  call_time: string;
  // Set by /import/parse: what this row already is, and what to do about it.
  // "on_project" | "in_roster" | "ambiguous" | "new"
  match_state?: string;
  match_id?: string | null;
  match_name?: string | null;
  differs?: { field: string; pasted: string | null; existing: string | null }[];
  // "add" | "skip" | "update" — the producer's choice, which the API obeys.
  action?: string;
  // UI only: this row is typing a new department rather than picking one.
  // Lives on the row rather than in a set of indexes so that removing a row
  // can't shift the flag onto its neighbour. Stripped before the POST.
  deptCustom?: boolean;
}

export default function CrewPage() {
  const { id } = useParams<{ id: string }>();
  // useSWR caches by key (the URL), so a page you've already visited this
  // session shows its last-known data immediately instead of blanking to a
  // skeleton again — then quietly revalidates in the background. Every place
  // below that used to call setCrew/setRoster now calls mutate() instead, with
  // `revalidate: false` since the API's own response is already the correct
  // new state; a background refetch would just repeat work we already did.
  const { data: crew = [], isLoading: crewLoading, mutate: mutateCrew } =
    useSWR<CrewMember[]>(`/api/projects/${id}/crew`, api.get);
  const { data: roster = [], error: rosterFetchError, mutate: mutateRoster } =
    useSWR<RosterEntry[]>("/api/roster?type=crew", api.get);
  // Only the screens are flagged (plan §11) — the job itself, and whether
  // this day belongs to one, is real either way, but the "From this job's
  // hires" button only shows on the Jobs version.
  const { betaJobs } = useBeta();
  const { data: project } = useSWR<ProjectSlim>(betaJobs ? `/api/projects/${id}` : null, api.get);
  const { data: jobHires = [], mutate: mutateJobHires } =
    useSWR<Hire[]>(betaJobs && project?.job_id ? `/api/jobs/${project.job_id}/hires` : null, api.get);
  const rosterError = rosterFetchError
    ? (rosterFetchError instanceof Error ? rosterFetchError.message : "Could not load your roster.")
    : "";
  // Presets, plus every department already in use on this project, plus every
  // department on the producer's roster. The roster half is what makes a
  // department they invented survive into the next job: custom departments
  // aren't stored anywhere of their own, so before this they were derived only
  // from the current project's crew and silently vanished on a new project.
  const deptOptions = useMemo(
    () => Array.from(new Set([
      ...DEPARTMENTS,
      ...crew.map((m) => m.department),
      ...roster.map((r) => r.department),
    ].filter((d): d is string => !!d))),
    [crew, roster],
  );
  const [mode, setMode] = useState<"closed" | "roster" | "hires" | "new" | "import">("closed");
  const [rosterSearch, setRosterSearch] = useState("");
  const [rosterCallTimes, setRosterCallTimes] = useState<Record<string, string>>({});
  const [addingFromRoster, setAddingFromRoster] = useState<string | null>(null);
  const [hiresSearch, setHiresSearch] = useState("");
  const [hireCallTimes, setHireCallTimes] = useState<Record<string, string>>({});
  const [addingFromHire, setAddingFromHire] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("");
  const [phone, setPhone] = useState("");
  const [callTime, setCallTime] = useState("");
  const [department, setDepartment] = useState("General Crew");
  const [customDepartment, setCustomDepartment] = useState("");
  const [editCustomDept, setEditCustomDept] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Kept apart from `error` so a bad call time highlights the field that
  // produced it instead of only naming the problem at the foot of the form.
  const [callTimeError, setCallTimeError] = useState<string | null>(null);
  const [editTimeError, setEditTimeError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<EditFields>({ name: "", email: "", role: "", phone: "", call_time: "", department: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [bulkTime, setBulkTime] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [addingToRoster, setAddingToRoster] = useState<string | null>(null);
  const [inlineDeptSaving, setInlineDeptSaving] = useState<string | null>(null);
  const [hideContactSaving, setHideContactSaving] = useState<string | null>(null);
  const [wantsPdfSaving, setWantsPdfSaving] = useState<string | null>(null);
  const [inlineCallSaving, setInlineCallSaving] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  // Separate from the row drag so a department block and a crew member can't
  // both think they're being dropped.
  const [deptDragIndex, setDeptDragIndex] = useState<number | null>(null);
  const [deptDragOverIndex, setDeptDragOverIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [importText, setImportText] = useState("");
  const [importParsing, setImportParsing] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportPreviewMember[]>([]);
  /* Adding one person at a time has always saved them to the Roster too, so
   * import matches it. On by default, and stated rather than silent — thirty at
   * once is worth seeing, where one at a time is not. Off is there for a crowd
   * of one-off extras nobody wants in their address book. */
  const [saveToRoster, setSaveToRoster] = useState(true);
  const [importPhase, setImportPhase] = useState<"input" | "preview">("input");
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const { show: showToast, node: toastNode } = useToast();

  // First time through this project (no crew yet, nothing cached): open the
  // add form so the user can start typing immediately instead of clicking
  // "Add new". Guarded to fire once — otherwise removing the last crew member
  // later would reopen this form every time the list became empty again.
  const autoOpenedNew = useRef(false);
  useEffect(() => {
    if (!crewLoading && !autoOpenedNew.current) {
      autoOpenedNew.current = true;
      if (crew.length === 0) setMode("new");
    }
  }, [crewLoading, crew.length]);

  const crewEmailSet = new Set(crew.map((m) => m.email.toLowerCase()));
  const rosterEmailSet = new Set(roster.map((e) => e.email?.toLowerCase()).filter(Boolean));
  const availableRoster = roster.filter((e) => !e.email || !crewEmailSet.has(e.email.toLowerCase()));
  const filteredRoster = rosterSearch.trim()
    ? availableRoster.filter((e) => [e.name, e.role, e.email, e.department].some((f) => f?.toLowerCase().includes(rosterSearch.toLowerCase())))
    : availableRoster;

  // Hired on the job but not yet on THIS day's crew — matched the same way
  // availableRoster is, by email, since a hire someone added by hand (no
  // hire_id yet) is still the same person as far as this list is concerned.
  const availableHires = jobHires.filter((h) => !h.days.some((d) => d.id === id) && (!h.email || !crewEmailSet.has(h.email.toLowerCase())));
  const filteredHires = hiresSearch.trim()
    ? availableHires.filter((h) => [h.name, h.role, h.email, h.department].some((f) => f?.toLowerCase().includes(hiresSearch.toLowerCase())))
    : availableHires;

  async function addFromHire(entry: Hire) {
    setAddingFromHire(entry.id);
    const ct = hireCallTimes[entry.id] || null;
    try {
      const member = await api.post<CrewMember>(`/api/projects/${id}/crew`, {
        hire_id: entry.id,
        roster_id: entry.roster_id,
        name: entry.name,
        email: entry.email ?? "",
        role: entry.role ?? "",
        phone: entry.phone || null,
        call_time: ct || null,
        department: entry.department || null,
      });
      mutateCrew((prev) => [...(prev ?? []), member], false);
      mutateJobHires();
      setHireCallTimes((prev) => { const n = { ...prev }; delete n[entry.id]; return n; });
    } catch (err) {
      console.error(err);
    } finally {
      setAddingFromHire(null);
    }
  }

  async function addFromRoster(entry: RosterEntry) {
    setAddingFromRoster(entry.id);
    const ct = rosterCallTimes[entry.id] || null;
    try {
      const member = await api.post<CrewMember>(`/api/projects/${id}/crew`, {
        // Carry the link, so a correction made on this job can travel back to
        // the person's Roster entry instead of stopping here.
        roster_id: entry.id,
        name: entry.name,
        email: entry.email ?? "",
        role: entry.role ?? "",
        phone: entry.phone || null,
        call_time: ct || null,
        department: entry.department || null,
      });
      mutateCrew((prev) => [...(prev ?? []), member], false);
      setRosterCallTimes((prev) => { const n = { ...prev }; delete n[entry.id]; return n; });
    } catch (err) {
      console.error(err);
    } finally {
      setAddingFromRoster(null);
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError(""); setCallTimeError(null);
    try {
      const resolvedDept = department === "__custom__" ? (customDepartment || null) : (department || null);
      const member = await api.post<CrewMember>(`/api/projects/${id}/crew`, {
        name, email, role, phone: phone || null, call_time: callTime || null,
        department: resolvedDept,
      });
      mutateCrew((prev) => [...(prev ?? []), member], false);
      api.post("/api/roster", { name, email: email || null, phone: phone || null, role: role || null, department: resolvedDept, type: "crew" }).catch(() => {});
      setName(""); setEmail(""); setRole(""); setPhone(""); setCallTime(""); setDepartment("General Crew"); setCustomDepartment("");
      showToast(`${member.name} added to crew`);
    } catch (err) {
      // A refused time belongs on the time field. Anything else has no one
      // field to point at, so it stays where it is.
      const onTimeField = timeError(err);
      setCallTimeError(onTimeField);
      setError(onTimeField ? "" : err instanceof Error ? err.message : "Failed to add crew member");
    } finally { setSaving(false); }
  }

  function startEdit(member: CrewMember) {
    setEditTimeError(null);
    const dept = member.department ?? "";
    // Checked against the live option list, not the presets — a department
    // already in use is a normal choice by now, not something to retype.
    const isCustom = dept !== "" && !deptOptions.includes(dept);
    setEditingId(member.id);
    setEditFields({ name: member.name, email: member.email, role: member.role, phone: member.phone ?? "", call_time: callTimeValue(member), department: isCustom ? "__custom__" : dept });
    setEditCustomDept(isCustom ? dept : "");
  }

  async function handleSave(memberId: string) {
    setEditSaving(true); setEditTimeError(null);
    try {
      const updated = await api.put<CrewMember>(`/api/projects/${id}/crew/${memberId}`, {
        name: editFields.name, email: editFields.email, role: editFields.role,
        phone: editFields.phone || null, call_time: editFields.call_time || null,
        department: editFields.department === "__custom__" ? (editCustomDept || null) : (editFields.department || null),
      });
      mutateCrew((prev) => prev?.map((m) => m.id === memberId ? updated : m), false);
      setEditingId(null);
      showToast("Changes saved");
    } catch (err) {
      // A refused time belongs on the time field. Anything else has no one
      // field to point at, so it stays where it is.
      const onTimeField = timeError(err);
      setEditTimeError(onTimeField);
      if (!onTimeField) showToast(err instanceof Error ? err.message : "Failed to save changes");
    } finally { setEditSaving(false); }
  }

  async function handleRemove(crewId: string) {
    if (confirmRemove !== crewId) { setConfirmRemove(crewId); return; }
    setConfirmRemove(null);
    await api.delete(`/api/projects/${id}/crew/${crewId}`);
    mutateCrew((prev) => prev?.filter((m) => m.id !== crewId), false);
    // They're back on "From this job's hires" — which reads each hire's days,
    // so it has to be refetched, not just filtered.
    mutateJobHires();
  }

  async function setAllCallTimes() {
    if (!bulkTime) return;
    setBulkBusy(true);
    try {
      const updated = await Promise.all(
        crew.map((m) => api.put<CrewMember>(`/api/projects/${id}/crew/${m.id}`, { call_time: bulkTime }))
      );
      mutateCrew(updated, false);
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to set call times"); }
    finally { setBulkBusy(false); }
  }

  async function shiftCallTimes(mins: number) {
    const withTime = crew.filter((m) => m.call_time);
    if (!withTime.length) return;
    setBulkBusy(true);
    try {
      const updated = await Promise.all(
        withTime.map((m) => api.put<CrewMember>(`/api/projects/${id}/crew/${m.id}`, {
          call_time: addMinutes(m.call_time!, mins),
        }))
      );
      mutateCrew((prev) => prev?.map((m) => updated.find((u) => u.id === m.id) ?? m), false);
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to shift call times"); }
    finally { setBulkBusy(false); }
  }

  async function handleAddToRoster(member: CrewMember) {
    setAddingToRoster(member.id);
    try {
      const entry = await api.post<RosterEntry>("/api/roster", {
        name: member.name,
        email: member.email || null,
        phone: member.phone || null,
        role: member.role || null,
        department: member.department || null,
        type: "crew",
      });
      mutateRoster((prev) => [...(prev ?? []), entry], false);
    } catch (err) { console.error(err); }
    finally { setAddingToRoster(null); }
  }

  async function handleInlineDept(member: CrewMember, dept: string) {
    setInlineDeptSaving(member.id);
    try {
      const updated = await api.put<CrewMember>(`/api/projects/${id}/crew/${member.id}`, {
        name: member.name, email: member.email, role: member.role,
        phone: member.phone || null, call_time: member.call_time || null,
        department: dept || null,
      });
      mutateCrew((prev) => prev?.map((m) => m.id === member.id ? updated : m), false);
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to update department"); }
    finally { setInlineDeptSaving(null); }
  }

  // Keeps this person's phone and email off the printed call sheet. They still
  // receive it — delivery uses the stored address, not what's on the sheet.
  async function handleToggleHideContact(member: CrewMember) {
    setHideContactSaving(member.id);
    try {
      const updated = await api.put<CrewMember>(`/api/projects/${id}/crew/${member.id}`, {
        hide_contact: !member.hide_contact,
      });
      mutateCrew((prev) => prev?.map((m) => m.id === member.id ? updated : m), false);
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to update contact visibility"); }
    finally { setHideContactSaving(null); }
  }

  // Attach a PDF copy to this person's email. Off by default — crew read the
  // sheet inline on a phone; the attachment is for whoever files or prints it.
  async function handleToggleWantsPdf(member: CrewMember) {
    setWantsPdfSaving(member.id);
    try {
      const updated = await api.put<CrewMember>(`/api/projects/${id}/crew/${member.id}`, {
        wants_pdf: !member.wants_pdf,
      });
      mutateCrew((prev) => prev?.map((m) => m.id === member.id ? updated : m), false);
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to update PDF setting"); }
    finally { setWantsPdfSaving(null); }
  }

  async function handleInlineCallTime(member: CrewMember, ct: string) {
    setInlineCallSaving(member.id);
    try {
      const updated = await api.put<CrewMember>(`/api/projects/${id}/crew/${member.id}`, {
        name: member.name, email: member.email, role: member.role,
        phone: member.phone || null, call_time: ct || null,
        department: member.department || null,
      });
      mutateCrew((prev) => prev?.map((m) => m.id === member.id ? updated : m), false);
    // No catch: the failure belongs on the field the producer typed into, so it
    // propagates to InlineCallTime, which keeps the bad text visible and prints
    // the API's reason underneath it.
    } finally { setInlineCallSaving(null); }
  }

  function updatePreviewMember(idx: number, field: keyof ImportPreviewMember, value: string) {
    setImportPreview((prev) => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m));
  }

  // Switching into "new department" clears whatever was parsed, so the typed
  // name starts empty rather than appending to a preset the import guessed.
  function setPreviewDeptCustom(idx: number, on: boolean) {
    setImportPreview((prev) => prev.map((m, i) =>
      i === idx ? { ...m, deptCustom: on, department: on ? "" : m.department } : m));
  }

  async function handleParse() {
    if (!importText.trim()) return;
    setImportParsing(true);
    setImportError("");
    try {
      const result = await api.post<{ members: ImportPreviewMember[] }>(
        `/api/projects/${id}/crew/import/parse`,
        { text: importText },
        { timeoutMs: SLOW_TIMEOUT_MS }
      );
      setImportPreview(result.members.map((m) => ({
        name: m.name || "",
        role: m.role || "",
        email: m.email || "",
        phone: m.phone || "",
        department: m.department || "",
        call_time: m.call_time || "",
        // The verdict the API just computed. An explicit shape is used here to
        // keep UI-only flags out of the row — but it silently drops anything the
        // API starts sending, which is exactly what happened when these were
        // added: the match was computed, returned, and thrown away, so every row
        // read as "New" and nothing was ever flagged.
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

  /* What a pasted row already is, and what to do about it.
   *
   * Shown in the review table rather than as a dialog, because this is where a
   * producer is already reading rows and deciding. The tool proposes a default
   * and never acts on it alone — silently dropping a row somebody pasted on
   * purpose is the failure worth avoiding. */
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
          {/* Say WHY these were called the same person — a shared email or phone
              under a different spelling is otherwise baffling. */}
          {filedAs && (
            <span style={{ color: "var(--text-muted)" }}> as &ldquo;{member.match_name}&rdquo;</span>
          )}
        </div>

        {/* Not a duplicate to drop — a producer holding a newer call sheet than
            the app has. Only the fields that actually moved, so the exception
            stands out rather than adding to the reading. */}
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
    const valid = importPreview
      .filter((m) => m.name.trim())
      // Explicit shape rather than a rest-spread: deptCustom is a UI flag and
      // has no business in the request body.
      .map((m) => ({
        name: m.name, role: m.role, email: m.email,
        phone: m.phone, department: m.department, call_time: m.call_time,
        // The verdict travels back so confirm can link without re-deciding,
        // and the action is the producer's override.
        match_state: m.match_state, match_id: m.match_id, action: m.action ?? "add",
      }));
    if (!valid.length) return;
    setImportBusy(true);
    try {
      const created = await api.post<CrewMember[]>(
        `/api/projects/${id}/crew/import/confirm`,
        { members: valid, save_to_roster: saveToRoster }
      );
      mutateCrew((prev) => [...(prev ?? []), ...created], false);
      setMode("closed");
      setImportText("");
      setImportPreview([]);
      setImportPhase("input");
      showToast(`${created.length} crew member${created.length === 1 ? "" : "s"} imported`);
    } catch {
      setImportError("Import failed. Please try again.");
    } finally {
      setImportBusy(false);
    }
  }

  function close() {
    setMode("closed");
    setRosterSearch("");
    setHiresSearch("");
    setError("");
    setImportText("");
    setImportPreview([]);
    setImportPhase("input");
    setImportError("");
  }

  // Department grouping, in the order each department first appears in the crew
  // list. This deliberately matches how the call sheet groups them — it used to
  // render a fixed canonical order here instead, so the order a producer saw on
  // this page was not the order the crew received.
  const anyHasDepartment = crew.some((m) => m.department);
  const crewGroups: { label: string; members: CrewMember[] }[] = [];
  if (anyHasDepartment) {
    const byDept = new Map<string, CrewMember[]>();
    for (const m of crew) {
      const key = m.department || "__none__";
      if (!byDept.has(key)) byDept.set(key, []);
      byDept.get(key)!.push(m);
    }
    // Map preserves insertion order, so this is first-appearance order.
    for (const [dept, members] of byDept) {
      if (dept === "__none__") continue;
      crewGroups.push({ label: dept, members });
    }
    // Crew with no department last — they're the leftovers, not a real block.
    if (byDept.has("__none__")) {
      crewGroups.push({ label: "", members: byDept.get("__none__")! });
    }
  }

  // Flattened render order — drag handles index into this sequence.
  const orderedCrew = anyHasDepartment ? crewGroups.flatMap((g) => g.members) : crew;
  const orderIndex = new Map(orderedCrew.map((m, i) => [m.id, i]));

  // Persist a flat crew order as contiguous sort_order values. Department order
  // is an emergent property of this — whichever department's members come first
  // is the block that renders first, on this page and on the sheet alike.
  async function persistOrder(flat: CrewMember[]) {
    const withOrders = flat.map((m, i) => ({ ...m, sort_order: i }));
    mutateCrew(withOrders, false);
    try {
      await Promise.all(withOrders.map((m) => api.put(`/api/projects/${id}/crew/${m.id}`, { sort_order: m.sort_order })));
    } catch (err) { showToast(err instanceof Error ? err.message : "Failed to save new order"); }
  }

  async function handleDrop(toIdx: number) {
    if (dragIndex === null || dragIndex === toIdx) { setDragIndex(null); setDragOverIndex(null); return; }
    const reordered = [...orderedCrew];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(toIdx, 0, moved);
    setDragIndex(null); setDragOverIndex(null);
    await persistOrder(reordered);
  }

  // Move a whole department block. Members keep their order within the block;
  // only the blocks move relative to each other.
  // Crew with no department are always rendered last, so that block can't be
  // moved and nothing can be moved below it — the grouping would just put it
  // back and the control would look broken.
  const movableDeptCount = crewGroups.filter((g) => g.label).length;

  async function moveDept(fromIdx: number, toIdx: number) {
    if (fromIdx === toIdx || toIdx < 0 || toIdx >= movableDeptCount) return;
    const groups = [...crewGroups];
    const [moved] = groups.splice(fromIdx, 1);
    groups.splice(toIdx, 0, moved);
    await persistOrder(groups.flatMap((g) => g.members));
  }

  async function handleDeptDrop(toIdx: number) {
    if (deptDragIndex === null || deptDragIndex === toIdx) { setDeptDragIndex(null); setDeptDragOverIndex(null); return; }
    const from = deptDragIndex;
    setDeptDragIndex(null); setDeptDragOverIndex(null);
    await moveDept(from, toIdx);
  }


  function memberEditRow(member: CrewMember) {
    return (
      <tr key={member.id}>
        <td />
        <td>
          <input aria-label="Name" value={editFields.name} onChange={(e) => setEditFields((f) => ({ ...f, name: e.target.value }))} className="field-input" />
        </td>
        <td>
          <input aria-label="Role" value={editFields.role} onChange={(e) => setEditFields((f) => ({ ...f, role: e.target.value }))} className="field-input" />
        </td>
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
        <td>
          <select
            aria-label="Department"
            value={editFields.department}
            onChange={(e) => { setEditFields((f) => ({ ...f, department: e.target.value })); if (e.target.value !== "__custom__") setEditCustomDept(""); }}
            className="field-input"
          >
            <option value="">—</option>
            {withExtra(deptOptions, editFields.department).map((d) => <option key={d} value={d}>{d}</option>)}
            <option disabled>──────────</option>
            <option value="__custom__">+ Add Department</option>
          </select>
          {editFields.department === "__custom__" && (
            <input
              aria-label="Custom department"
              value={editCustomDept}
              onChange={(e) => setEditCustomDept(e.target.value)}
              placeholder="e.g. Stunts…"
              className="field-input mt-1"
              autoFocus
            />
          )}
        </td>
        {/* Email and phone used to be stacked under Name and Role, because the
            table had no columns for them. It does now, so they sit where the
            header says they are. */}
        <td>
          <input aria-label="Email" type="email" placeholder="Email" value={editFields.email} onChange={(e) => setEditFields((f) => ({ ...f, email: e.target.value }))} className="field-input" />
        </td>
        <td>
          <input aria-label="Phone" type="tel" placeholder="Phone" value={editFields.phone} onChange={(e) => setEditFields((f) => ({ ...f, phone: e.target.value }))} className="field-input" />
        </td>
        {/* Contact visibility and PDF save on their own; keep columns aligned while editing. */}
        <td />
        <td />
        <td><span className={member.confirmed_at ? "badge-confirmed" : "badge-pending"}>{member.confirmed_at ? "Confirmed" : "Pending"}</span></td>
        <td className="text-right whitespace-nowrap sticky-actions">
          <button onClick={() => handleSave(member.id)} disabled={editSaving} className="btn btn-ghost btn-sm mr-1">{editSaving ? "Saving…" : "Save"}</button>
          <button onClick={() => setEditingId(null)} className="btn btn-ghost btn-sm">Cancel</button>
        </td>
      </tr>
    );
  }

  function memberDisplayRow(member: CrewMember) {
    const rowIdx = orderIndex.get(member.id)!;
    return (
      <tr
        key={member.id}
        onDragOver={(e) => { e.preventDefault(); if (dragOverIndex !== rowIdx) setDragOverIndex(rowIdx); }}
        onDrop={() => handleDrop(rowIdx)}
        style={{
          opacity: dragIndex === rowIdx ? 0.4 : 1,
          background: dragOverIndex === rowIdx && dragIndex !== rowIdx ? "var(--bg-surface)" : undefined,
        }}
      >
        <td>
          {/* Drag handle and arrows share this cell so the table gains no
              width. Drag is unchanged on desktop; the arrows are the path for
              touch and keyboard, which drag events never reach. */}
          <span
            draggable
            onDragStart={() => setDragIndex(rowIdx)}
            onDragEnd={() => { setDragIndex(null); setDragOverIndex(null); }}
            className="cursor-grab select-none text-base"
            style={{ color: "var(--text-muted)" }}
            title="Drag to reorder"
          >
            ⠿
          </span>
        </td>
        <td className="font-medium" style={{ color: "var(--text-primary)" }}>
          {member.name}
          {offDates.has(member.id) && (
            <span className="block text-xs font-normal mt-0.5" style={{ color: "var(--warning)" }}>
              Not working this day by their dates
            </span>
          )}
          {/* Under the name, not in the pinned actions column: it made that
              column ~210px wide, and a pinned column that wide sat over Call
              time on a laptop screen. */}
          {member.email && !rosterEmailSet.has(member.email.toLowerCase()) && (
            <button
              onClick={() => handleAddToRoster(member)}
              disabled={addingToRoster === member.id}
              className="block text-left text-xs font-normal mt-0.5"
              style={{ color: "var(--text-muted)" }}
            >
              {addingToRoster === member.id ? "Saving…" : "+ Add to Roster"}
            </button>
          )}
        </td>
        <td style={{ color: "var(--text-secondary)" }}>{member.role}</td>
        {/* Call time sits right after Role (Patrick, 2026-09-28): it's the column
            this page is for, and at laptop widths the table scrolls — whatever
            comes last hides under the pinned actions. */}
        <td>
          <InlineCallTime
            initial={callTimeValue(member)}
            saving={inlineCallSaving === member.id}
            onSave={(v) => handleInlineCallTime(member, v)}
          />
        </td>
        <td>
          <select
            aria-label={`Department for ${member.name}`}
            value={member.department ?? ""}
            onChange={(e) => handleInlineDept(member, e.target.value)}
            disabled={inlineDeptSaving === member.id}
            className="field-input py-1 text-sm"
            // A fixed width, not minWidth. A select in an auto-layout table
            // sizes to its longest option — "Catering & Craft Services" was
            // claiming ~320px and pushing Remove off the right edge.
            style={{ color: "var(--text-secondary)", width: "11.5rem" }}
          >
            <option value="">—</option>
            {withExtra(deptOptions, member.department).map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </td>
        <td style={{ color: "var(--text-secondary)" }}>{member.email || "—"}</td>
        {/* A phone number split across two lines is unusable — the same rule the
            call sheet and the Roster both landed on. */}
        <td className="whitespace-nowrap" style={{ color: "var(--text-secondary)" }}>{member.phone || "—"}</td>
        <td>
          <button
            onClick={() => handleToggleHideContact(member)}
            disabled={hideContactSaving === member.id}
            aria-pressed={member.hide_contact}
            aria-label={`${member.hide_contact ? "Show" : "Hide"} phone and email for ${member.name} on the call sheet`}
            title={
              member.hide_contact
                ? "Phone and email are hidden on the call sheet. They still receive it."
                : "Phone and email appear on the call sheet"
            }
            className="btn btn-ghost btn-sm whitespace-nowrap"
            style={{ color: member.hide_contact ? "var(--accent-hover)" : "var(--text-muted)" }}
          >
            {hideContactSaving === member.id ? "…" : member.hide_contact ? "Hidden" : "Shown"}
          </button>
        </td>
        <td>
          <button
            onClick={() => handleToggleWantsPdf(member)}
            disabled={wantsPdfSaving === member.id}
            aria-pressed={member.wants_pdf}
            aria-label={`${member.wants_pdf ? "Stop attaching" : "Attach"} a PDF copy for ${member.name}`}
            title={
              member.wants_pdf
                ? "A PDF copy is attached to their email"
                : "No PDF attached — they still get the sheet in the email"
            }
            className="btn btn-ghost btn-sm whitespace-nowrap"
            style={{ color: member.wants_pdf ? "var(--accent-hover)" : "var(--text-muted)" }}
          >
            {wantsPdfSaving === member.id ? "…" : member.wants_pdf ? "PDF" : "—"}
          </button>
        </td>
        <td><span className={member.confirmed_at ? "badge-confirmed" : "badge-pending"}>{member.confirmed_at ? "Confirmed" : "Pending"}</span></td>
        <td className="text-right whitespace-nowrap sticky-actions">
          <button onClick={() => startEdit(member)} className="btn btn-ghost btn-sm mr-1">Edit</button>
          <button
            onClick={() => handleRemove(member.id)}
            onMouseLeave={() => { if (confirmRemove === member.id) setConfirmRemove(null); }}
            className={confirmRemove === member.id ? "btn btn-danger btn-sm" : "btn btn-ghost btn-sm"}
            style={confirmRemove !== member.id ? { color: "var(--danger)" } : {}}
          >
            {confirmRemove === member.id ? "Sure?" : "Remove"}
          </button>
        </td>
      </tr>
    );
  }

  /* What the Import button will actually do — rows set to Skip are not imported,
   * so counting names would have the button promise "Import 1 person" while the
   * header above it said "0 to add, 1 skipped". Updating rows count too: they
   * change someone already here rather than adding anyone. */
  const importAddCount = importPreview.filter(
    (m) => m.name.trim() && (m.action ?? "add") === "add"
  ).length;
  const importUpdateCount = importPreview.filter(
    (m) => m.name.trim() && m.action === "update"
  ).length;
  const validImportCount = importAddCount + importUpdateCount;

  // Always offered, in every header state.
  //
  // It used to be hidden whenever the roster had nothing to add, which is
  // exactly backwards for the person who most needs to know the feature exists:
  // a new producer's roster is empty, so they never saw the button, and the
  // roster only fills up by adding people from these pages. The feature hid
  // itself from everyone who hadn't already found it.
  //
  // The panel now explains itself when empty rather than not opening at all.
  const rosterButton = (
    <button onClick={() => setMode("roster")} className="btn btn-success">
      From roster
    </button>
  );

  // Only once this day is known to belong to a job — hidden rather than shown
  // disabled, since a day from before Jobs (or a database without the
  // migration) simply has no hires to offer.
  // On this day's crew but not working it by their own job dates — the same
  // people the Shoot days card names. Only ever someone with a call time or a
  // confirmation here: untouched rows follow their dates off the day.
  const shootDate = project?.shoot_date;
  const offDates = new Set(shootDate ? (crew ?? []).filter((m) => {
    const h = m.hire_id ? jobHires.find((x) => x.id === m.hire_id) : null;
    return !!h?.effective_dates && !Object.values(h.effective_dates)
      .some((spans) => spans.some(([a, b]) => shootDate >= a && shootDate <= b));
  }).map((m) => m.id) : []);

  const hiresButton = betaJobs && project?.job_id ? (
    <button onClick={() => setMode("hires")} className="btn btn-success">
      From this job&rsquo;s hires
    </button>
  ) : null;

  // 5xl is shared with Talent and Agency & Client so the three people pages are
  // the same size when you click between them. It is also the narrowest step
  // that clears the table's 58rem (928px) minimum, so the nine columns still fit
  // without the horizontal scroll kicking in. 6xl fit too, but left dead space
  // and made this page visibly larger than its neighbours.
  return (
    /* Wider than the other project pages, on purpose. Eleven columns with an
       email address in them need about 76rem; at max-w-5xl the table overflowed
       and Edit/Remove sat off the right edge with no visible scrollbar — the
       exact failure the note above the table warns about. Crew is the widest
       table in the app and the only page that needs this. */
    <div className="max-w-7xl mx-auto px-4 md:px-8 py-10">
      {toastNode}
      {/* Both rows wrap: four buttons in one unbreakable row made the page
          ~575px wide on a phone, pushing the day menu button off screen. */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-8">
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Crew</h2>
        {mode === "closed" ? (
          <div className="flex flex-wrap gap-2">
            {rosterButton}
            {hiresButton}
            <button onClick={() => { setMode("import"); setImportPhase("input"); }} className="btn btn-secondary">
              Quick Import
            </button>
            <button onClick={() => setMode("new")} className="btn btn-primary">Add new</button>
          </div>
        ) : mode === "new" ? (
          <div className="flex flex-wrap gap-2">
            {rosterButton}
            {hiresButton}
            <button onClick={() => { setMode("import"); setImportPhase("input"); }} className="btn btn-secondary">
              Quick Import
            </button>
            <button onClick={close} className="btn btn-ghost">Done</button>
          </div>
        ) : (
          <button onClick={close} className="btn btn-ghost">Done</button>
        )}
      </div>

      {/* From roster */}
      {mode === "roster" && (
        <div className="card mb-6">
          <div className="px-5 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <input
              aria-label="Search roster"
              value={rosterSearch}
              onChange={(e) => setRosterSearch(e.target.value)}
              placeholder="Search roster…"
              className="field-input"
              autoFocus
            />
          </div>
          {rosterError ? (
            <div className="px-5 py-4">
              <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                Couldn&rsquo;t load your roster
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Nothing has been deleted — the request didn&rsquo;t go through. {rosterError}
              </p>
              <button onClick={() => mutateRoster()} className="btn btn-secondary btn-sm mt-3">Try again</button>
            </div>
          ) : filteredRoster.length === 0 ? (
            <div className="px-5 py-4">
              {rosterSearch ? (
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>No matches.</p>
              ) : roster.length === 0 ? (
                <>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    Your roster is empty
                  </p>
                  <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                    Everyone you add to a shoot is saved here, so next time you can pull them
                    in without retyping a name, email or phone number.
                  </p>
                </>
              ) : (
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                  Everyone on your roster is already on this shoot.
                </p>
              )}
            </div>
          ) : (
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
              {filteredRoster.map((entry) => (
                <div key={entry.id} className="flex items-center gap-4 px-5 py-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{entry.name}</p>
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                      {[entry.department, entry.role, entry.email].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  <TimeInput
                    value={rosterCallTimes[entry.id] ?? ""}
                    onChange={(v) => setRosterCallTimes((prev) => ({ ...prev, [entry.id]: v }))}
                    className="shrink-0"
                    style={{ width: "9rem" }}
                  />
                  <button
                    onClick={() => addFromRoster(entry)}
                    disabled={addingFromRoster === entry.id}
                    className="btn btn-primary btn-sm shrink-0"
                  >
                    {addingFromRoster === entry.id ? "Adding…" : "Add"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* From this job's hires */}
      {mode === "hires" && (
        <div className="card mb-6">
          <div className="px-5 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <input
              aria-label="Search this job's hires"
              value={hiresSearch}
              onChange={(e) => setHiresSearch(e.target.value)}
              placeholder="Search this job's hires…"
              className="field-input"
              autoFocus
            />
          </div>
          {filteredHires.length === 0 ? (
            <div className="px-5 py-4">
              {hiresSearch ? (
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>No matches.</p>
              ) : jobHires.length === 0 ? (
                <>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    Nobody&rsquo;s hired on this job yet
                  </p>
                  <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                    Hire people on the job&rsquo;s Pre-production tab, then pull them onto
                    whichever days they&rsquo;re actually working from here.
                  </p>
                </>
              ) : (
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                  Everyone hired on this job is already on this day&rsquo;s crew.
                </p>
              )}
            </div>
          ) : (
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
              {filteredHires.map((entry) => (
                <div key={entry.id} className="flex items-center gap-4 px-5 py-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{entry.name}</p>
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                      {[entry.department, entry.role, entry.email].filter(Boolean).join(" · ")}
                    </p>
                    {/* Informational only — nothing here pre-selects or filters
                        anyone. Whether a day's worth of hires match this day is
                        a producer's call for now (see docs/job-layer-plan.md §6). */}
                    {entry.dates_text && (
                      <p className="text-xs mt-0.5 whitespace-pre-line" style={{ color: "var(--text-secondary)" }}>
                        {entry.dates_text}
                      </p>
                    )}
                  </div>
                  <TimeInput
                    value={hireCallTimes[entry.id] ?? ""}
                    onChange={(v) => setHireCallTimes((prev) => ({ ...prev, [entry.id]: v }))}
                    className="shrink-0"
                    style={{ width: "9rem" }}
                  />
                  <button
                    onClick={() => addFromHire(entry)}
                    disabled={addingFromHire === entry.id}
                    className="btn btn-primary btn-sm shrink-0"
                  >
                    {addingFromHire === entry.id ? "Adding…" : "Add"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Paste import — input */}
      {mode === "import" && importPhase === "input" && (
        <div className="card p-5 mb-6 space-y-4">
          <div>
            <label className="field-label">Paste crew data</label>
            <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
              Paste rows from a spreadsheet or contact list — names, roles, emails, and phone numbers will be extracted automatically.
            </p>
            <textarea
              aria-label="Paste crew data"
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              rows={8}
              placeholder={"Jane Smith\tDirector of Photography\tjane@example.com\t555-1234\nBob Jones\tGaffer\tbob@example.com\t555-5678"}
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
              {(() => {
                /* State the outcome before it happens. A producer pasting thirty
                   rows should see what is about to be added, skipped and updated
                   without counting the table themselves. */
                const acts = importPreview.filter((m) => m.name.trim())
                  .map((m) => m.action ?? "add");
                const n = (a: string) => acts.filter((x) => x === a).length;
                const parts = [
                  `${n("add")} to add`,
                  n("skip") ? `${n("skip")} skipped` : "",
                  n("update") ? `${n("update")} to update` : "",
                ].filter(Boolean);
                return `${acts.length} ${acts.length === 1 ? "person" : "people"} found — ${parts.join(", ")}`;
              })()}
            </p>
            <button onClick={() => setImportPhase("input")} className="btn btn-ghost btn-sm">← Back</button>
          </div>
          <div className="px-5 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-secondary)", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={saveToRoster}
                onChange={(e) => setSaveToRoster(e.target.checked)}
              />
              {(() => {
                const n = importPreview.filter(
                  (m) => m.name.trim() && (m.action ?? "add") !== "skip" && m.match_state !== "in_roster"
                ).length;
                return n === 0
                  ? "Everyone here is already in your Roster"
                  : `Also save ${n} ${n === 1 ? "person" : "people"} to my Roster`;
              })()}
            </label>
          </div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>Name</th><th>Role</th><th>Department</th><th>Email</th><th>Phone</th><th>Call time</th><th>Already known?</th><th /></tr>
              </thead>
              <tbody>
                {importPreview.map((member, idx) => (
                  <tr key={idx}>
                    <td><input aria-label="Name" value={member.name} onChange={(e) => updatePreviewMember(idx, "name", e.target.value)} className="field-input" /></td>
                    <td><input aria-label="Role" value={member.role} onChange={(e) => updatePreviewMember(idx, "role", e.target.value)} className="field-input" /></td>
                    <td>
                      <select
                        aria-label="Department"
                        // Show what was parsed, even if it isn't spelled like a
                        // preset. Blanking it here made an imported "Wardrobe"
                        // look dropped when it had actually come through fine.
                        value={member.deptCustom ? "__custom__" : member.department}
                        onChange={(e) => {
                          const value = e.target.value;
                          if (value === "__custom__") {
                            setPreviewDeptCustom(idx, true);
                          } else {
                            setPreviewDeptCustom(idx, false);
                            updatePreviewMember(idx, "department", value);
                          }
                        }}
                        className="field-input py-1 text-sm"
                      >
                        <option value="">—</option>
                        {/* While typing a new one, `department` holds the in-progress
                            text — don't echo it back as a phantom option. */}
                        {withExtra(deptOptions, member.deptCustom ? "" : member.department).map((d) => <option key={d} value={d}>{d}</option>)}
                        <option disabled>──────────</option>
                        <option value="__custom__">+ Add Department</option>
                      </select>
                      {member.deptCustom && (
                        <input
                          aria-label="New department"
                          value={member.department}
                          onChange={(e) => updatePreviewMember(idx, "department", e.target.value)}
                          placeholder="e.g. Stunts…"
                          className="field-input py-1 text-sm mt-1"
                          autoFocus
                        />
                      )}
                    </td>
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
              {importBusy
                ? "Importing…"
                : validImportCount === 0
                ? "Nothing to import"
                : importUpdateCount === 0
                ? `Import ${importAddCount} ${importAddCount === 1 ? "person" : "people"}`
                : importAddCount === 0
                ? `Update ${importUpdateCount}`
                : `Import ${importAddCount}, update ${importUpdateCount}`}
            </button>
            {importError && <p className="text-xs" style={{ color: "var(--danger)" }}>{importError}</p>}
          </div>
        </div>
      )}

      {/* New person form */}
      {mode === "new" && (
        <div className="card p-5 mb-6">
          <form onSubmit={handleAdd} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="field-label">Name</label><input required aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} className="field-input" /></div>
              <div><label className="field-label">Role</label><input required aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Director of Photography" className="field-input" /></div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div><label className="field-label">Email</label><input required aria-label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="field-input" /></div>
              <div><label className="field-label">Phone</label><input aria-label="Phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(555) 555-5555" className="field-input" /></div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="field-label">Department</label>
                <select
                  aria-label="Department"
                  value={department}
                  onChange={(e) => { setDepartment(e.target.value); if (e.target.value !== "__custom__") setCustomDepartment(""); }}
                  className="field-input"
                >
                  <option value="">— No department —</option>
                  {withExtra(deptOptions, department).map((d) => <option key={d} value={d}>{d}</option>)}
                  <option disabled>──────────</option>
                  <option value="__custom__">+ Add Department</option>
                </select>
                {department === "__custom__" && (
                  <input
                    aria-label="Custom department"
                    value={customDepartment}
                    onChange={(e) => setCustomDepartment(e.target.value)}
                    placeholder="e.g. Stunts, Pyrotechnics…"
                    className="field-input mt-2"
                    autoFocus
                  />
                )}
              </div>
              <div><label className="field-label">Call time</label><TimeInput value={callTime} onChange={(v) => { setCallTime(v); setCallTimeError(null); }} error={callTimeError} /></div>
            </div>
            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button type="submit" disabled={saving} className="btn btn-primary">
              {saving ? "Adding…" : "Add to crew"}
            </button>
          </form>
        </div>
      )}

      {crewLoading ? (
        <TableSkeleton columns={7} />
      ) : crew.length === 0 ? (
        <div className="card p-8 text-center space-y-3">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No crew members yet.</p>
        </div>
      ) : (
        <>
          {/* Bulk call time toolbar */}
          <div
            className="flex items-center gap-4 flex-wrap px-4 py-3 rounded-lg mb-3"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium shrink-0" style={{ color: "var(--text-muted)" }}>Set all</label>
              <TimeInput
                value={bulkTime}
                onChange={setBulkTime}
                onKeyDown={(e) => { if (e.key === "Enter") setAllCallTimes(); }}
                style={{ width: "9rem" }}
              />
              <button onClick={setAllCallTimes} disabled={!bulkTime || bulkBusy} className="btn btn-secondary btn-sm shrink-0">Apply</button>
            </div>
            <div className="h-4 shrink-0" style={{ width: "1px", background: "var(--border)" }} />
            {/* Wraps: six shift buttons in one row were the last thing
                widening the page on a phone. */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-medium mr-1 shrink-0" style={{ color: "var(--text-muted)" }}>Shift</span>
              {[-60, -30, -15, 15, 30, 60].map((m) => (
                <button
                  key={m}
                  onClick={() => shiftCallTimes(m)}
                  disabled={bulkBusy || crew.every((c) => !c.call_time)}
                  className="btn btn-ghost btn-sm tabular-nums"
                  style={{ minWidth: "2.75rem" }}
                >
                  {m > 0 ? `+${m}` : m}m
                </button>
              ))}
            </div>
          </div>

          {crew.length > 1 && (
            <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
              Drag <span className="select-none">⠿</span> to set the order crew appears on the call sheet
              {anyHasDepartment
                ? " — on a person to move them within their department, or on a department heading to move the whole block."
                : "."}
            </p>
          )}

          <div className="card overflow-x-auto">
            {/* .data-table is width:100%, so the table can never grow past its
                container and the overflow-x-auto above it never has anything to
                scroll. Columns just compress until the nowrap actions cell
                overflows the table box and Remove is clipped away with no way to
                reach it. A min-width lets the table exceed the card on a narrow
                window, which is what makes the wrapper actually scroll. */}
            <table className="data-table" style={{ minWidth: "76rem" }}>
              <thead>
                <tr>
                  {/* Person fields first (name, role, department, email, phone),
                      then the job ones. Same order and same information as the
                      Roster, so the two pages read the same way. */}
                  <th /><th>Name</th><th>Role</th><th>Call time</th><th>Department</th><th>Email</th><th>Phone</th><th>On sheet</th><th>PDF</th><th>Status</th><th className="sticky-actions" />
                </tr>
              </thead>
              <tbody>
                {anyHasDepartment
                  ? crewGroups.flatMap(({ label, members }, groupIdx) => [
                      <tr
                        key={`dept-${label || "none"}`}
                        onDragOver={(e) => { if (deptDragIndex !== null && label) { e.preventDefault(); setDeptDragOverIndex(groupIdx); } }}
                        onDrop={() => { if (label) handleDeptDrop(groupIdx); }}
                        style={{
                          background: deptDragOverIndex === groupIdx && deptDragIndex !== groupIdx
                            ? "var(--bg-elevated)"
                            : "var(--bg-surface)",
                          opacity: deptDragIndex === groupIdx ? 0.4 : 1,
                        }}
                      >
                        <td
                          colSpan={11}
                          className="text-xs font-bold uppercase tracking-wider py-2 px-3"
                          // Accent rail + bolder, brighter label so a department
                          // heading reads as a block boundary at a glance rather
                          // than as one more crew row.
                          style={{
                            color: "var(--text-secondary)",
                            borderLeft: `3px solid ${label ? "var(--accent)" : "var(--border)"}`,
                          }}
                        >
                          <span className="inline-flex items-center gap-2">
                            {label && (
                              <>
                                <span
                                  draggable
                                  onDragStart={() => setDeptDragIndex(groupIdx)}
                                  onDragEnd={() => { setDeptDragIndex(null); setDeptDragOverIndex(null); }}
                                  className="cursor-grab select-none text-sm"
                                  // A different glyph from the crew rows' ⠿ so
                                  // the two handles aren't mistaken for each
                                  // other — bars for a block, dots for a person.
                                  style={{ color: "var(--accent-hover)" }}
                                  title={`Drag to move ${label} up or down the call sheet`}
                                  aria-label={`Reorder the ${label} block`}
                                >
                                  ☰
                                </span>
                              </>
                            )}
                            {label || "No Department"}
                          </span>
                        </td>
                      </tr>,
                      ...members.map((m) => editingId === m.id ? memberEditRow(m) : memberDisplayRow(m)),
                    ])
                  : crew.map((m) => editingId === m.id ? memberEditRow(m) : memberDisplayRow(m))
                }
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
