"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, SLOW_TIMEOUT_MS } from "@/lib/api";
import AppFooter from "@/components/AppFooter";
import { TableSkeleton } from "@/components/Skeleton";

const DEPARTMENTS = [
  "General Crew", "Above the Line",
  "Camera Department", "Grip & Electric", "Sound Department", "Art Department", "Production",
  "Wardrobe/Costume", "Hair & Makeup", "Transportation", "Catering & Craft Services",
];

type RosterType = "crew" | "talent" | "client";
const ROSTER_TYPES: RosterType[] = ["crew", "talent", "client"];
const TYPE_LABEL: Record<RosterType, { one: string; many: string; tab: string }> = {
  crew: { one: "crew member", many: "crew", tab: "Crew" },
  talent: { one: "talent", many: "talent", tab: "Talent" },
  client: { one: "client", many: "clients", tab: "Clients" },
};

// Mirrors backend services/call_sheet_import.py. Checked here too so a wrong
// file is refused instantly instead of after the upload.
const MAX_SHEET_BYTES = 10 * 1024 * 1024;

interface PasteRow {
  name: string;
  role: string;
  department: string;
  organization: string;
  email: string;
  phone: string;
  /** Which tab this person lands on. A paste is always the active tab's type;
   * a call sheet carries all three, and the producer can move a row. */
  type: RosterType;
  /** "in_roster" | "ambiguous" | "new" — or "moved" once the producer changes
   * the type. Absent only if the API couldn't classify. */
  matchState?: string;
  matchName?: string | null;
  /** Fields where the import and the saved entry disagree. */
  differs?: string[];
}

// Shape returned by the Claude-backed /api/roster/import/parse and
// /api/roster/import/call-sheet endpoints — both classify each row against the
// caller's Roster (backend services/import_match.py classify_against_roster).
interface ParsedMember {
  name?: string | null;
  role?: string | null;
  email?: string | null;
  phone?: string | null;
  department?: string | null;
  organization?: string | null;
  type?: string | null;
  match_state?: string;
  match_name?: string | null;
  differs?: { field: string }[];
}

function asRosterType(t: string | null | undefined): RosterType {
  return t === "talent" || t === "client" ? t : "crew";
}

/* The one mapping from either import's API response to preview rows — a paste
 * (/roster/import/parse) and a call sheet (/roster/import/call-sheet) answer in
 * the same shape. It's an explicit shape rather than a spread, so UI-only state
 * stays out of the confirm body; the cost is that a field the API adds is
 * dropped until it's carried here on purpose (tests/import-preview-shape.test.ts
 * checks the ones that matter). `fallbackType` covers a row the API didn't type. */
function toPreviewRows(members: ParsedMember[], fallbackType: RosterType): PasteRow[] {
  return members
    .filter((m) => (m.name ?? "").trim())
    .map((m) => ({
      name: m.name ?? "",
      role: m.role ?? "",
      department: m.department ?? "",
      organization: m.organization ?? "",
      email: m.email ?? "",
      phone: m.phone ?? "",
      type: m.type ? asRosterType(m.type) : fallbackType,
      matchState: m.match_state,
      matchName: m.match_name ?? null,
      differs: (m.differs ?? []).map((d) => d.field),
    }));
}

interface RosterEntry {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  department: string | null;
  organization: string | null;
  type: string;
  company: string | null;
  day_rate: string | null;
  rate_note: string | null;
  agency: string | null;
  agent_name: string | null;
  agent_email: string | null;
  agent_phone: string | null;
  // Talent: home city and portfolio link (the talent hold sheet's Based and
  // Link columns). Only http(s) links are accepted, server side.
  based?: string | null;
  portfolio_url?: string | null;
  /* What saving this entry propagated to the producer's projects. Present only
   * when something was actually changed elsewhere. */
  synced?: { rows_updated: number; projects_updated: number; sheets_now_stale: number } | null;
}

interface DupGroup {
  type: string;
  /** "shared_contact" (an email or phone in common) or "same_name". */
  reason: string;
  /** What they have in common — shown so the producer can judge the evidence. */
  shared: string[];
  entries: RosterEntry[];
}

interface EditFields {
  name: string;
  email: string;
  phone: string;
  role: string;
  department: string;
  organization: string;
  company: string;
  dayRate: string;
  rateNote: string;
  agency: string;
  agentName: string;
  agentEmail: string;
  agentPhone: string;
  based: string;
  portfolioUrl: string;
}

export default function RosterPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<"crew" | "talent" | "client">("crew");
  const [crewRoster, setCrewRoster] = useState<RosterEntry[]>([]);
  const [talentRoster, setTalentRoster] = useState<RosterEntry[]>([]);
  const [clientRoster, setClientRoster] = useState<RosterEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState("");
  const [department, setDepartment] = useState("General Crew");
  const [organization, setOrganization] = useState("");
  const [company, setCompany] = useState("");
  const [dayRate, setDayRate] = useState("");
  const [rateNote, setRateNote] = useState("");
  const [agency, setAgency] = useState("");
  const [agentName, setAgentName] = useState("");
  const [agentEmail, setAgentEmail] = useState("");
  const [agentPhone, setAgentPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<EditFields>({
    name: "", email: "", phone: "", role: "", department: "", organization: "",
    company: "", dayRate: "", rateNote: "", agency: "", agentName: "", agentEmail: "", agentPhone: "", based: "", portfolioUrl: "",
  });
  const [editSaving, setEditSaving] = useState(false);
  const [customDepartment, setCustomDepartment] = useState("");
  const [editCustomDept, setEditCustomDept] = useState("");
  const [inlineDeptSaving, setInlineDeptSaving] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showPaste, setShowPaste] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [pasteRows, setPasteRows] = useState<PasteRow[] | null>(null);
  const [parsing, setParsing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  /* The call sheet upload. `readingSheet` is the file's name while the model
   * reads it — several seconds, so the card says so rather than looking stuck;
   * `sheetName` marks a preview as having come from a sheet, which is what
   * turns on the per-type sections and the Roster status column. */
  const [readingSheet, setReadingSheet] = useState<string | null>(null);
  const [sheetName, setSheetName] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const sheetInputRef = useRef<HTMLInputElement>(null);
  /* A call sheet can fill all three tabs at once, and only one is visible — so
   * after an import, say where everyone went. */
  const [importNote, setImportNote] = useState<string | null>(null);

  // Never swallow this. A failed load used to render an ordinary empty roster,
  // which reads as "my saved people are gone" rather than "the request failed".
  const loadRoster = useCallback(() => {
    setLoading(true); setLoadError("");
    Promise.all([
      api.get<RosterEntry[]>("/api/roster?type=crew"),
      api.get<RosterEntry[]>("/api/roster?type=talent"),
      api.get<RosterEntry[]>("/api/roster?type=client"),
    ]).then(([crew, talent, client]) => {
      setCrewRoster(crew);
      setTalentRoster(talent);
      setClientRoster(client);
    }).catch((err) => {
      setLoadError(err instanceof Error ? err.message : "Could not load your roster.");
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadRoster(); }, [loadRoster]);

  function resetForm() {
    setName(""); setEmail(""); setPhone(""); setRole(""); setDepartment("General Crew"); setOrganization(""); setCustomDepartment("");
    setCompany(""); setDayRate(""); setRateNote(""); setAgency(""); setAgentName(""); setAgentEmail(""); setAgentPhone("");
  }

  function switchTab(tab: "crew" | "talent" | "client") {
    setActiveTab(tab);
    setShowForm(false);
    setShowPaste(false);
    setPasteText("");
    setPasteRows(null);
    setSheetName(null);
    setImportError("");
    setEditingId(null);
    setSearch("");
    resetForm();
  }

  const sorter = (a: RosterEntry, b: RosterEntry) => a.name.localeCompare(b.name);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError("");
    try {
      const entry = await api.post<RosterEntry>("/api/roster", {
        name,
        email: email || null,
        phone: phone || null,
        role: role || null,
        department: activeTab === "crew" ? (department === "__custom__" ? (customDepartment || null) : (department || null)) : null,
        organization: activeTab === "client" ? (organization || null) : null,
        type: activeTab,
        company: activeTab === "crew" ? (company || null) : null,
        day_rate: activeTab === "crew" || activeTab === "talent" ? (dayRate || null) : null,
        rate_note: activeTab === "crew" || activeTab === "talent" ? (rateNote || null) : null,
        agency: activeTab === "talent" ? (agency || null) : null,
        agent_name: activeTab === "talent" ? (agentName || null) : null,
        agent_email: activeTab === "talent" ? (agentEmail || null) : null,
        agent_phone: activeTab === "talent" ? (agentPhone || null) : null,
      });
      // The API answers with the existing entry when this person is already
      // on the Roster (same email or phone). Replace it rather than listing it
      // twice, and say so — otherwise "Add" looks like it did nothing, or made
      // a duplicate.
      const current = activeTab === "crew" ? crewRoster : activeTab === "talent" ? talentRoster : clientRoster;
      const existed = current.some((e) => e.id === entry.id);
      const upsert = (prev: RosterEntry[]) =>
        (existed ? prev.map((e) => (e.id === entry.id ? entry : e)) : [...prev, entry]).sort(sorter);
      if (activeTab === "crew") setCrewRoster(upsert);
      else if (activeTab === "talent") setTalentRoster(upsert);
      else setClientRoster(upsert);
      setSyncNote(existed
        ? `${entry.name} is already on your Roster, so nothing new was added. Anything they were missing was filled in; use Edit to change the rest.`
        : null);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add");
    } finally { setSaving(false); }
  }

  function openPaste() {
    setShowForm(false);
    setShowPaste(true);
    setPasteText("");
    setPasteRows(null);
    setSheetName(null);
    setImportError("");
    setImportNote(null);
  }

  function closePaste() {
    setShowPaste(false);
    setPasteText("");
    setPasteRows(null);
    setSheetName(null);
    setImportError("");
  }

  async function handleParse() {
    if (!pasteText.trim()) return;
    setParsing(true);
    setImportError("");
    try {
      const result = await api.post<{ members: ParsedMember[] }>("/api/roster/import/parse", {
        text: pasteText,
        type: activeTab,
      }, { timeoutMs: SLOW_TIMEOUT_MS });
      const rows = toPreviewRows(result.members, activeTab);
      if (rows.length === 0) {
        setImportError("No people found in that text. Check it contains names and try again.");
        return;
      }
      setPasteRows(rows);
    } catch {
      setImportError("Couldn't read that text. Try again, or add contacts manually.");
    } finally {
      setParsing(false);
    }
  }

  /* Read the people off an old call sheet PDF. The PDF goes to the API as-is;
   * the API sends it to Claude, which finds crew, talent and client contacts
   * in one go, and nothing is kept. The rows land in the same preview a paste
   * does, and Import sends them through the same confirm endpoint. */
  async function handleCallSheet(file: File) {
    setImportError("");
    const looksLikePdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!looksLikePdf) {
      setImportError("That isn't a PDF. Export or print the call sheet to PDF and try again.");
      return;
    }
    if (file.size > MAX_SHEET_BYTES) {
      setImportError(`That file is ${(file.size / (1024 * 1024)).toFixed(1)} MB. Call sheets can be up to 10 MB.`);
      return;
    }
    setReadingSheet(file.name);
    try {
      const result = await api.uploadFile<{ members: ParsedMember[] }>(
        "/api/roster/import/call-sheet", file, "application/pdf",
      );
      const rows = toPreviewRows(result.members, "crew");
      if (rows.length === 0) {
        setImportError("No crew, talent or client contacts found on that call sheet.");
        return;
      }
      setSheetName(file.name);
      setPasteRows(rows);
    } catch (err) {
      const status = (err as { status?: number } | null)?.status;
      setImportError(
        status === 429
          ? "That's a lot of call sheets in one hour — try again later, or paste the list instead."
          : status && status < 500 && err instanceof Error
          ? err.message   // the API's own wording: not a PDF, too big, too many pages, locked
          : "Couldn't read that call sheet. Try again, or paste the list instead."
      );
    } finally {
      setReadingSheet(null);
      if (sheetInputRef.current) sheetInputRef.current.value = "";
    }
  }

  function updatePasteRow(i: number, field: Exclude<keyof PasteRow, "type" | "matchState" | "matchName" | "differs">, value: string) {
    setPasteRows((prev) => (prev ? prev.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)) : prev));
  }

  function setPasteRowType(i: number, type: RosterType) {
    // The Roster status was worked out against the old type's entries, so it no
    // longer applies; confirm re-matches against the new type on the way in.
    setPasteRows((prev) => (prev ? prev.map((r, idx) => (idx === i
      ? { ...r, type, matchState: r.matchState ? "moved" : undefined, matchName: null, differs: [] }
      : r)) : prev));
  }

  function removePasteRow(i: number) {
    setPasteRows((prev) => (prev ? prev.filter((_, idx) => idx !== i) : prev));
  }

  async function handleImport() {
    if (!pasteRows) return;
    const valid = pasteRows.filter((r) => r.name.trim());
    if (valid.length === 0) {
      setImportError("Each contact needs a name.");
      return;
    }
    setImporting(true);
    setImportError("");
    // One confirm per type — the same endpoint and body a paste import uses,
    // which is also where matching and blank-filling happen. A paste only ever
    // has the active tab's type; a call sheet can have all three.
    const done: { type: RosterType; count: number }[] = [];
    try {
      for (const type of ROSTER_TYPES) {
        const ofType = valid.filter((r) => r.type === type);
        if (!ofType.length) continue;
        const added = await api.post<RosterEntry[]>("/api/roster/import/confirm", {
          type,
          members: ofType.map((r) => ({
            name: r.name.trim(),
            role: r.role.trim() || null,
            email: r.email.trim() || null,
            phone: r.phone.trim() || null,
            department: type === "crew" ? (r.department.trim() || null) : null,
            organization: type === "client" ? (r.organization.trim() || null) : null,
          })),
        });
        const merge = (prev: RosterEntry[]) => {
          const byId = new Map(prev.map((e) => [e.id, e]));
          for (const e of added) byId.set(e.id, e);
          return [...byId.values()].sort(sorter);
        };
        if (type === "crew") setCrewRoster(merge);
        else if (type === "talent") setTalentRoster(merge);
        else setClientRoster(merge);
        done.push({ type, count: ofType.length });
      }
      if (sheetName) {
        const parts = done.map(({ type, count }) => `${count} ${count === 1 ? TYPE_LABEL[type].one : TYPE_LABEL[type].many}`);
        const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
        setImportNote(
          `Imported ${list} from ${sheetName}.` +
          (done.some(({ type }) => type !== activeTab) ? " Each is on its own tab." : "")
        );
        loadDuplicates();
      }
      closePaste();
    } catch (err) {
      // Whatever already went in stays in — take those rows out of the preview
      // so trying again doesn't send them twice. (It would be harmless: confirm
      // matches them to the entries it just made. But it would look wrong.)
      if (done.length) {
        const imported = new Set(done.map((d) => d.type));
        setPasteRows((prev) => (prev ? prev.filter((r) => !imported.has(r.type)) : prev));
      }
      const reason = err instanceof Error ? err.message : "Import failed";
      setImportError(done.length
        ? `${done.map((d) => TYPE_LABEL[d.type].tab).join(" and ")} imported; the rest didn't go through. ${reason}`
        : reason);
    } finally {
      setImporting(false);
    }
  }

  async function handleInlineDept(entry: RosterEntry, dept: string) {
    setInlineDeptSaving(entry.id);
    try {
      const updated = await api.put<RosterEntry>(`/api/roster/${entry.id}`, {
        name: entry.name, email: entry.email || null, phone: entry.phone || null,
        role: entry.role || null, department: dept || null, organization: entry.organization || null,
      });
      setCrewRoster((prev) => prev.map((e) => e.id === entry.id ? updated : e));
    } catch (err) {
      setEditError(err instanceof Error ? `Couldn't change the department: ${err.message}` : "Couldn't change the department.");
    }
    finally { setInlineDeptSaving(null); }
  }

  function startEdit(entry: RosterEntry) {
    const dept = entry.department ?? "";
    const isCustom = dept !== "" && !DEPARTMENTS.includes(dept);
    setEditingId(entry.id);
    setEditFields({
      name: entry.name,
      email: entry.email ?? "",
      phone: entry.phone ?? "",
      role: entry.role ?? "",
      department: isCustom ? "__custom__" : dept,
      organization: entry.organization ?? "",
      company: entry.company ?? "",
      dayRate: entry.day_rate ?? "",
      rateNote: entry.rate_note ?? "",
      agency: entry.agency ?? "",
      agentName: entry.agent_name ?? "",
      agentEmail: entry.agent_email ?? "",
      agentPhone: entry.agent_phone ?? "",
      based: entry.based ?? "",
      portfolioUrl: entry.portfolio_url ?? "",
    });
    setEditCustomDept(isCustom ? dept : "");
  }

  /* What the last save changed beyond this page.
   *
   * Editing someone here now reaches their rows on jobs that haven't shot yet,
   * which is the point — but a producer who isn't told has had several projects
   * altered invisibly. The stale-sheet count matters just as much: propagation
   * updates rows, and a call sheet is stored HTML frozen at generation, so those
   * sheets still show the old details until they are regenerated. */
  const [syncNote, setSyncNote] = useState<string | null>(null);

  /* Entries that are probably one person. Detection is the half that matters —
   * nobody finds duplicates by scrolling 74 contacts — and the section removes
   * itself when there is nothing to show, like the setup checklist. */
  const [dupGroups, setDupGroups] = useState<DupGroup[]>([]);
  const [merging, setMerging] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [confirmMerge, setConfirmMerge] = useState<string | null>(null);
  const [mergeNote, setMergeNote] = useState<string | null>(null);

  const loadDuplicates = useCallback(() => {
    api.get<{ groups: DupGroup[] }>("/api/roster/duplicates")
      .then((r) => setDupGroups(r.groups))
      .catch(() => setDupGroups([]));   // a failure here must not break the page
  }, []);

  useEffect(() => { loadDuplicates(); }, [loadDuplicates]);

  async function handleMerge(group: DupGroup, keepId: string) {
    if (confirmMerge !== keepId) { setConfirmMerge(keepId); return; }
    setConfirmMerge(null);
    setMerging(keepId); setMergeNote(null);
    try {
      const res = await api.post<{ repointed: number; deleted: number; filled: string[] }>(
        "/api/roster/merge",
        { keep_id: keepId, drop_ids: group.entries.filter((e) => e.id !== keepId).map((e) => e.id) },
      );
      setMergeNote(
        `Merged ${res.deleted + 1} entries into one.` +
        (res.repointed ? ` ${res.repointed} project ${res.repointed === 1 ? "row" : "rows"} now point at it.` : "") +
        (res.filled.length ? ` Filled in ${res.filled.join(", ")}.` : "")
      );
      loadRoster();
      loadDuplicates();
    } catch (err) {
      setMergeNote(err instanceof Error ? err.message : "Could not merge those entries.");
    } finally { setMerging(null); }
  }

  async function handleSave(entryId: string) {
    // The server refuses to blank a name (it keeps the old one), so say so
    // here rather than closing the row as if it had saved.
    if (!editFields.name.trim()) { setEditError("A name is required."); return; }
    setEditSaving(true);
    setSyncNote(null);
    setEditError(null);
    try {
      const updated = await api.put<RosterEntry>(`/api/roster/${entryId}`, {
        name: editFields.name,
        email: editFields.email || null,
        phone: editFields.phone || null,
        role: editFields.role || null,
        department: editFields.department === "__custom__" ? (editCustomDept || null) : (editFields.department || null),
        organization: editFields.organization || null,
        // Only the fields this tab's form shows. An empty value now clears the
        // field (the backend saves what was sent), so a field the form hides
        // must be left out, not sent as null — or editing a crew member would
        // wipe agency details they got as talent.
        ...(activeTab === "crew" ? { company: editFields.company || null } : {}),
        ...(activeTab === "crew" || activeTab === "talent"
          ? { day_rate: editFields.dayRate || null, rate_note: editFields.rateNote || null } : {}),
        ...(activeTab === "talent" ? {
          agency: editFields.agency || null,
          agent_name: editFields.agentName || null,
          agent_email: editFields.agentEmail || null,
          agent_phone: editFields.agentPhone || null,
          based: editFields.based || null,
          portfolio_url: editFields.portfolioUrl || null,
        } : {}),
      });
      if (activeTab === "crew") {
        setCrewRoster((prev) => prev.map((e) => e.id === entryId ? updated : e));
      } else if (activeTab === "talent") {
        setTalentRoster((prev) => prev.map((e) => e.id === entryId ? updated : e));
      } else {
        setClientRoster((prev) => prev.map((e) => e.id === entryId ? updated : e));
      }
      setEditingId(null);
      if (updated.synced && updated.synced.projects_updated > 0) {
        const { projects_updated: n, sheets_now_stale: stale } = updated.synced;
        setSyncNote(
          `Updated on ${n} upcoming ${n === 1 ? "project" : "projects"}.` +
          (stale > 0
            ? ` ${stale} call ${stale === 1 ? "sheet needs" : "sheets need"} regenerating to show the change.`
            : "")
        );
      }
    } catch (err) {
      // Stays open with what was typed, and says why — a failed save used to
      // close the row as if it had worked.
      setEditError(err instanceof Error ? `Couldn't save: ${err.message}` : "Couldn't save that change.");
    }
    finally { setEditSaving(false); }
  }

  // Remove and Merge both delete an entry for good, so each asks first: the
  // first click turns the button into "Remove Dana?" / "Merge into this one?"
  // with a Cancel beside it; the second does it. (They used to act on the
  // first click — found testing staging, 2026-09-28.)
  async function handleRemove(entryId: string) {
    if (confirmRemove !== entryId) { setConfirmRemove(entryId); return; }
    setConfirmRemove(null);
    await api.delete(`/api/roster/${entryId}`);
    if (activeTab === "crew") {
      setCrewRoster((prev) => prev.filter((e) => e.id !== entryId));
    } else if (activeTab === "talent") {
      setTalentRoster((prev) => prev.filter((e) => e.id !== entryId));
    } else {
      setClientRoster((prev) => prev.filter((e) => e.id !== entryId));
    }
  }

  const roster = activeTab === "crew" ? crewRoster : activeTab === "talent" ? talentRoster : clientRoster;
  const filtered = search.trim()
    ? roster.filter((e) =>
        [e.name, e.role, e.email, e.department, e.organization].some(
          (f) => f?.toLowerCase().includes(search.toLowerCase())
        )
      )
    : roster;

  const anyHasDepartment = activeTab === "crew" && filtered.some((e) => e.department);

  const crewGroups: { label: string; entries: RosterEntry[] }[] = [];
  if (anyHasDepartment) {
    const byDept = new Map<string, RosterEntry[]>();
    for (const e of filtered) {
      const key = e.department || "__none__";
      if (!byDept.has(key)) byDept.set(key, []);
      byDept.get(key)!.push(e);
    }
    for (const dept of DEPARTMENTS) {
      if (byDept.has(dept)) {
        crewGroups.push({ label: dept, entries: byDept.get(dept)! });
        byDept.delete(dept);
      }
    }
    const unknowns = [...byDept.keys()].filter((k) => k !== "__none__").sort();
    for (const dept of unknowns) {
      crewGroups.push({ label: dept, entries: byDept.get(dept)! });
    }
    if (byDept.has("__none__")) {
      crewGroups.push({ label: "", entries: byDept.get("__none__")! });
    }
  }

  /* Whether an import row — pasted or off a call sheet — is already someone on
   * the Roster; the same labels the crew page's paste import uses, from the same
   * backend helper (import_match.classify_against_roster). Informational:
   * importing a match never makes a second entry, it only fills in what the
   * saved one is missing. Absent if classification failed server-side. */
  function importStatusLine(r: PasteRow) {
    const LABELS: Record<string, { text: string; colour: string; hint?: string }> = {
      in_roster: { text: "In your Roster", colour: "var(--accent-hover)", hint: "Only fills in what's missing" },
      ambiguous: { text: "Possible match", colour: "var(--text-muted)", hint: "Added as new — merge later if it's them" },
      new: { text: "New", colour: "var(--text-muted)" },
      moved: { text: "Checked on import", colour: "var(--text-muted)" },
    };
    const { text, colour, hint } = LABELS[r.matchState ?? "new"] ?? LABELS.new;
    const filedAs = r.matchName && r.matchName.trim().toLowerCase() !== r.name.trim().toLowerCase();
    const differs = r.differs ?? [];
    return (
      <div className="space-y-0.5 text-xs mt-1" style={{ maxWidth: "12rem" }}>
        <div style={{ color: colour }}>
          {text}
          {filedAs && <span style={{ color: "var(--text-muted)" }}> as &ldquo;{r.matchName}&rdquo;</span>}
        </div>
        {differs.length > 0 ? (
          <div style={{ color: "var(--text-muted)" }}>
            {differs.join(", ")} differ{differs.length === 1 ? "s" : ""} — the Roster keeps its own
          </div>
        ) : hint ? (
          <div style={{ color: "var(--text-muted)" }}>{hint}</div>
        ) : null}
      </div>
    );
  }

  /* One type's rows in the Quick Import preview. Rows keep their index in
   * pasteRows so edits land on the right one whichever table they're shown in. */
  function previewTable(type: RosterType, fromSheet: boolean) {
    const rows = (pasteRows ?? []).map((r, i) => ({ r, i })).filter(({ r }) => r.type === type);
    // A call sheet's table has an extra Type column, which squeezed every input
    // to a stub. Floor the widths; the table scrolls on a narrow screen instead.
    const w = (minWidth: string) => (fromSheet ? { minWidth } : undefined);
    return (
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              {fromSheet && <th>Type</th>}
              <th>Role</th>
              {type === "crew" && <th>Department</th>}
              {type === "client" && <th>Organization</th>}
              <th>Email</th>
              <th>Phone</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ r, i }) => (
              <tr key={i}>
                <td>
                  <input
                    aria-label="Name"
                    value={r.name}
                    onChange={(e) => updatePasteRow(i, "name", e.target.value)}
                    className="field-input"
                    style={w("9rem")}
                  />
                  {/* Under the name rather than its own column — it's about the
                      person, and a ninth column pushes Remove off the edge. */}
                  {r.matchState && importStatusLine(r)}
                </td>
                {fromSheet && (
                  <td>
                    <select
                      aria-label={`Type for ${r.name || `row ${i + 1}`}`}
                      value={r.type}
                      onChange={(e) => setPasteRowType(i, asRosterType(e.target.value))}
                      className="field-input py-1 text-sm"
                      style={{ minWidth: "6.5rem" }}
                    >
                      {ROSTER_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t].tab}</option>)}
                    </select>
                  </td>
                )}
                <td><input aria-label="Role" value={r.role} onChange={(e) => updatePasteRow(i, "role", e.target.value)} className="field-input" style={w("8rem")} /></td>
                {type === "crew" && (
                  <td>
                    <select
                      aria-label={`Department for row ${i + 1}`}
                      value={r.department}
                      onChange={(e) => updatePasteRow(i, "department", e.target.value)}
                      className="field-input py-1 text-sm"
                      style={w("9rem")}
                    >
                      <option value="">—</option>
                      {r.department && !DEPARTMENTS.includes(r.department) && (
                        <option value={r.department}>{r.department}</option>
                      )}
                      {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
                    </select>
                  </td>
                )}
                {type === "client" && (
                  <td><input aria-label="Organization" value={r.organization} onChange={(e) => updatePasteRow(i, "organization", e.target.value)} placeholder="Agency, Brand…" className="field-input" style={w("9rem")} /></td>
                )}
                <td><input aria-label="Email" type="email" value={r.email} onChange={(e) => updatePasteRow(i, "email", e.target.value)} className="field-input" style={w("11rem")} /></td>
                <td><input aria-label="Phone" type="tel" value={r.phone} onChange={(e) => updatePasteRow(i, "phone", e.target.value)} className="field-input" style={w("8.5rem")} /></td>
                <td>
                  <button
                    type="button"
                    onClick={() => removePasteRow(i)}
                    aria-label={`Remove ${r.name || `row ${i + 1}`}`}
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
    );
  }

  function crewEditRow(entry: RosterEntry) {
    return (
      <Fragment key={entry.id}>
      <tr>
        <td><input value={editFields.name} onChange={(e) => setEditFields((f) => ({ ...f, name: e.target.value }))} className="field-input" /></td>
        <td><input value={editFields.role} onChange={(e) => setEditFields((f) => ({ ...f, role: e.target.value }))} className="field-input" /></td>
        <td>
          <select
            aria-label="Department"
            value={editFields.department}
            onChange={(e) => { setEditFields((f) => ({ ...f, department: e.target.value })); if (e.target.value !== "__custom__") setEditCustomDept(""); }}
            className="field-input"
          >
            <option value="">—</option>
            {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
            <option disabled>──────────</option>
            <option value="__custom__">+ Add Department</option>
          </select>
          {editFields.department === "__custom__" && (
            <input
              value={editCustomDept}
              onChange={(e) => setEditCustomDept(e.target.value)}
              placeholder="e.g. Stunts…"
              className="field-input mt-1"
              autoFocus
            />
          )}
        </td>
        <td><input type="email" value={editFields.email} onChange={(e) => setEditFields((f) => ({ ...f, email: e.target.value }))} className="field-input" /></td>
        <td><input type="tel" value={editFields.phone} onChange={(e) => setEditFields((f) => ({ ...f, phone: e.target.value }))} className="field-input" /></td>
        <td className="text-right whitespace-nowrap">
          <button onClick={() => handleSave(entry.id)} disabled={editSaving} className="btn btn-ghost btn-sm mr-1">{editSaving ? "Saving…" : "Save"}</button>
          <button onClick={() => setEditingId(null)} className="btn btn-ghost btn-sm">Cancel</button>
        </td>
      </tr>
      {/* Rate and company are deliberately not table columns (they're
          producer-only and rarely needed at a glance) — this row only exists
          while editing, spanning the same width the department heading rows
          already use. */}
      <tr style={{ background: "var(--bg-elevated)" }}>
        <td colSpan={6} className="px-3 pb-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div><label className="field-label">Company</label><input aria-label="Company" value={editFields.company} onChange={(e) => setEditFields((f) => ({ ...f, company: e.target.value }))} className="field-input" /></div>
            <div><label className="field-label">Day rate</label><input aria-label="Day rate" value={editFields.dayRate} onChange={(e) => setEditFields((f) => ({ ...f, dayRate: e.target.value }))} className="field-input" /></div>
            <div><label className="field-label">Rate note</label><textarea aria-label="Rate note" rows={2} value={editFields.rateNote} onChange={(e) => setEditFields((f) => ({ ...f, rateNote: e.target.value }))} placeholder={"Shoot day rate = $800\nTravel day rate = $400"} className="field-input" /></div>
          </div>
        </td>
      </tr>
      </Fragment>
    );
  }

  function crewDisplayRow(entry: RosterEntry) {
    return (
      <tr key={entry.id}>
        <td className="font-medium" style={{ color: "var(--text-primary)" }}>{entry.name}</td>
        <td style={{ color: "var(--text-secondary)" }}>{entry.role ?? "—"}</td>
        <td>
          <select
            aria-label={`Department for ${entry.name}`}
            value={entry.department ?? ""}
            onChange={(e) => handleInlineDept(entry, e.target.value)}
            disabled={inlineDeptSaving === entry.id}
            className="field-input py-1 text-sm"
            style={{ color: "var(--text-secondary)", minWidth: "10rem" }}
          >
            <option value="">—</option>
            {/* Their own department, when it isn't one of the standard ones —
                without it the select showed "—" for someone listed under
                WARDROBE, and one careless change would have overwritten it. */}
            {entry.department && !DEPARTMENTS.includes(entry.department) && (
              <option value={entry.department}>{entry.department}</option>
            )}
            {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </td>
        <td style={{ color: "var(--text-secondary)" }}>{entry.email ?? "—"}</td>
        {/* A phone number split across two lines is unusable — same rule the
            call sheet learned. */}
        <td className="whitespace-nowrap" style={{ color: "var(--text-secondary)" }}>{entry.phone ?? "—"}</td>
        <td className="text-right whitespace-nowrap">
          <button onClick={() => startEdit(entry)} className="btn btn-ghost btn-sm mr-1" aria-label={`Edit ${entry.name}`}>Edit</button>
          {confirmRemove === entry.id ? (
                          <>
                            <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm" aria-label={`Confirm removing ${entry.name}`}>Remove {entry.name.split(" ")[0]}?</button>
                            <button onClick={() => setConfirmRemove(null)} className="btn btn-ghost btn-sm" aria-label={`Keep ${entry.name}`}>Cancel</button>
                          </>
                        ) : (
                          <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm" aria-label={`Remove ${entry.name}`}>Remove</button>
                        )}
        </td>
      </tr>
    );
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="px-6 py-3 flex items-center justify-between"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <span className="text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>SET&gt;READY</span>
      </header>

      <main className="flex-1 w-full max-w-6xl mx-auto px-4 md:px-6 py-10">
        <button onClick={() => router.back()} className="text-xs mb-6 block" style={{ color: "var(--text-muted)" }}>← Back</button>

        {/* Saving here can change rows on other projects, so say so. Silence
            would mean a producer's jobs were edited without them knowing. */}
        {mergeNote && (
          <div className="card px-4 py-3 mb-6 flex items-start justify-between gap-4" role="status">
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>{mergeNote}</span>
            <button onClick={() => setMergeNote(null)} className="text-xs"
              style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }}>
              Dismiss
            </button>
          </div>
        )}

        {/* Possible duplicates. Present only when there are any, and gone the
            moment they are resolved — the producer is never nagged about a clean
            roster. Each group shows WHAT the entries share, because a shared
            phone can be a duplicate, a couple, or an assistant who books for
            someone, and only the producer knows which. Nothing merges without
            them choosing who survives. */}
        {dupGroups.length > 0 && (
          <div className="card p-5 mb-6" style={{ borderLeft: "3px solid var(--accent)" }}>
            <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
              {dupGroups.length === 1 ? "1 possible duplicate" : `${dupGroups.length} possible duplicates`}
            </h3>
            <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
              These look like the same person. Pick the entry to keep — the others
              are folded into it and every project pointing at them follows.
            </p>

            {dupGroups.map((g, gi) => (
              <div key={gi} className="mb-4 pb-4" style={{ borderBottom: gi < dupGroups.length - 1 ? "1px solid var(--border)" : "none" }}>
                <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
                  {g.reason === "shared_contact"
                    ? <>Share {g.shared.map((v) => <code key={v}>{v}</code>).reduce((a, b) => <>{a}, {b}</>)}</>
                    : <>Same name, and nothing recorded that says otherwise</>}
                  {" · "}{g.type}
                </p>
                <ul className="space-y-1">
                  {g.entries.map((e) => (
                    <li key={e.id} className="flex items-center justify-between gap-3 py-1">
                      <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                        {e.name}
                        <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>
                          {[e.role, e.email, e.phone].filter(Boolean).join(" · ") || "no details"}
                        </span>
                      </span>
                      {confirmMerge === e.id ? (
                        <span className="flex items-center gap-1 whitespace-nowrap">
                          <button onClick={() => handleMerge(g, e.id)} disabled={merging !== null} className="btn btn-primary btn-sm">
                            {merging === e.id ? "Merging…" : "Merge into this one?"}
                          </button>
                          <button onClick={() => setConfirmMerge(null)} disabled={merging !== null} className="btn btn-ghost btn-sm">Cancel</button>
                        </span>
                      ) : (
                        <button
                          onClick={() => handleMerge(g, e.id)}
                          disabled={merging !== null}
                          className="btn btn-ghost btn-sm whitespace-nowrap"
                          title="Keeps this entry and deletes the others, after asking"
                        >
                          Keep this one
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {importNote && (
          <div className="card px-4 py-3 mb-6 flex items-start justify-between gap-4" role="status">
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>{importNote}</span>
            <button
              type="button"
              onClick={() => setImportNote(null)}
              className="text-xs"
              style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }}
            >
              Dismiss
            </button>
          </div>
        )}

        {editError && (
          <div className="card px-4 py-3 mb-6 flex items-start justify-between gap-4" role="alert"
            style={{ borderColor: "var(--danger)" }}>
            <span className="text-sm" style={{ color: "var(--danger)" }}>{editError}</span>
            <button onClick={() => setEditError(null)} className="text-xs"
              style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }} aria-label="Dismiss">
              Dismiss
            </button>
          </div>
        )}
        {syncNote && (
          <div
            className="card px-4 py-3 mb-6 flex items-start justify-between gap-4"
            role="status"
          >
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>{syncNote}</span>
            <button
              onClick={() => setSyncNote(null)}
              className="text-xs"
              style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }}
              aria-label="Dismiss"
            >
              Dismiss
            </button>
          </div>
        )}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Master Roster</h2>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Saved contacts you can pull into any project</p>
          </div>
          <div className="flex gap-2 shrink-0">
            <button onClick={openPaste} className="btn btn-secondary">Quick Import</button>
            <button
              onClick={() => { setShowPaste(false); setShowForm(!showForm); }}
              className="btn btn-primary"
            >
              {showForm ? "Done" : activeTab === "crew" ? "Add crew" : activeTab === "talent" ? "Add talent" : "Add contact"}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 p-1 rounded-lg" style={{ background: "var(--bg-surface)", width: "fit-content" }}>
          {(["crew", "talent", "client"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => switchTab(tab)}
              className="px-4 py-1.5 rounded text-sm font-medium transition-colors"
              style={{
                background: activeTab === tab ? "var(--bg-elevated)" : "transparent",
                color: activeTab === tab ? "var(--text-primary)" : "var(--text-muted)",
                border: activeTab === tab ? "1px solid var(--border)" : "1px solid transparent",
              }}
            >
              {tab === "crew" ? "Crew" : tab === "talent" ? "Talent" : "Clients"}
            </button>
          ))}
        </div>

        {/* Add form */}
        {showForm && (
          <form onSubmit={handleAdd} className="card p-5 mb-6 space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="field-label">Name</label>
                <input required aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} className="field-input" />
              </div>
              <div>
                <label className="field-label">Role / Title</label>
                <input
                  aria-label="Role / Title"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  placeholder={activeTab === "crew" ? "Gaffer, Key Grip…" : activeTab === "talent" ? "Actor, Model…" : "Art Director…"}
                  className="field-input"
                />
              </div>
            </div>
            {activeTab === "crew" ? (
              <div>
                <label className="field-label">Department</label>
                <select
                  aria-label="Department"
                  value={department}
                  onChange={(e) => { setDepartment(e.target.value); if (e.target.value !== "__custom__") setCustomDepartment(""); }}
                  className="field-input"
                >
                  <option value="">— No department —</option>
                  {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
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
            ) : activeTab === "client" ? (
              <div>
                <label className="field-label">Organization</label>
                <input
                  aria-label="Organization"
                  value={organization}
                  onChange={(e) => setOrganization(e.target.value)}
                  placeholder="Agency, Brand, Studio…"
                  className="field-input"
                />
              </div>
            ) : null}
            {/* This person's own contact info comes right after their name —
                deliberately BEFORE the agent block below, so "Email" here and
                "Agent email" further down are never sitting next to each other
                with nothing to tell them apart. */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="field-label">Email</label>
                <input type="email" aria-label="Email" value={email} onChange={(e) => setEmail(e.target.value)} className="field-input" />
              </div>
              <div>
                <label className="field-label">Phone</label>
                <input type="tel" aria-label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(555) 555-5555" className="field-input" />
              </div>
            </div>
            {activeTab === "crew" && (
              <div>
                <label className="field-label">Company</label>
                <input aria-label="Company" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Rays Productions" className="field-input" />
              </div>
            )}
            {(activeTab === "crew" || activeTab === "talent") && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="field-label">Day rate</label>
                  <input aria-label="Day rate" value={dayRate} onChange={(e) => setDayRate(e.target.value)} placeholder="$650" className="field-input" />
                </div>
                <div>
                  <label className="field-label">Rate note</label>
                  <textarea aria-label="Rate note" rows={2} value={rateNote} onChange={(e) => setRateNote(e.target.value)} placeholder={"10-hour scout/shoot day, or one rate per line:\nShoot day rate = $800"} className="field-input" />
                </div>
              </div>
            )}
            {activeTab === "talent" && (
              <div className="pt-1" style={{ borderTop: "1px solid var(--border)" }}>
                {/* Whose contact this is only reads correctly with a label —
                    "Agent email" alone, right under this person's own email
                    above, was easy to misread as a second address for them. */}
                <p className="text-xs font-semibold uppercase tracking-wide mb-3 mt-3" style={{ color: "var(--text-muted)" }}>
                  Represented by — not {name.trim() || "this person"}&rsquo;s own contact info
                </p>
                <div className="space-y-4">
                  <div>
                    <label className="field-label">Agency</label>
                    <input aria-label="Agency" value={agency} onChange={(e) => setAgency(e.target.value)} placeholder="CAA" className="field-input" />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div><label className="field-label">Agent name</label><input aria-label="Agent name" value={agentName} onChange={(e) => setAgentName(e.target.value)} className="field-input" /></div>
                    <div><label className="field-label">Agent email</label><input type="email" aria-label="Agent email" value={agentEmail} onChange={(e) => setAgentEmail(e.target.value)} className="field-input" /></div>
                    <div><label className="field-label">Agent phone</label><input type="tel" aria-label="Agent phone" value={agentPhone} onChange={(e) => setAgentPhone(e.target.value)} className="field-input" /></div>
                  </div>
                </div>
              </div>
            )}
            {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
            <button type="submit" disabled={saving} className="btn btn-primary">{saving ? "Adding…" : "Add"}</button>
          </form>
        )}

        {/* Quick Import — input */}
        {showPaste && !pasteRows && readingSheet && (
          <div className="card p-5 mb-6" role="status" aria-live="polite">
            <p className="text-sm font-medium flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span className="inline-block w-2 h-2 rounded-full animate-pulse" style={{ background: "var(--accent)" }} aria-hidden="true" />
              Reading your call sheet…
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Finding the crew, talent and client contacts on <span style={{ color: "var(--text-secondary)" }}>{readingSheet}</span>.
              This usually takes 15–30 seconds.
            </p>
          </div>
        )}

        {showPaste && !pasteRows && !readingSheet && (
          <div className="card p-5 mb-6 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="md:col-span-2">
                <label className="field-label">
                  Paste {activeTab === "crew" ? "crew" : activeTab === "talent" ? "talent" : "contact"} data
                </label>
                <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
                  Paste rows from a spreadsheet or contact list — names, roles,{activeTab === "client" ? " organizations," : ""} emails, and phone numbers will be extracted automatically.
                </p>
                <textarea
                  aria-label="Paste data"
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  rows={8}
                  placeholder={
                    activeTab === "client"
                      ? "Jane Doe\tCreative Director\tAcme Agency\tjane@acme.com\t555-1234"
                      : "Jane Smith\tDirector of Photography\tjane@example.com\t555-1234\nBob Jones\tGaffer\tbob@example.com\t555-5678"
                  }
                  className="field-input font-mono text-sm"
                  style={{ resize: "vertical" }}
                  autoFocus
                />
              </div>
              {/* The other way in: an old call sheet. Covers all three tabs at
                  once — a sheet lists crew, talent and client together — so the
                  wording doesn't follow the active tab the way the paste box does. */}
              <div className="flex flex-col">
                <span className="field-label">Or upload an old call sheet</span>
                <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
                  Crew, talent and client contacts are all picked up. Rates never are.
                </p>
                <div
                  onDragOver={(e) => { e.preventDefault(); if (!dragActive) setDragActive(true); }}
                  onDragLeave={(e) => {
                    // Moving onto the button inside still counts as over the zone.
                    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragActive(false);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragActive(false);
                    const file = e.dataTransfer.files?.[0];
                    if (file) handleCallSheet(file);
                  }}
                  className="flex-1 rounded-lg px-4 py-5 flex flex-col items-center justify-center text-center gap-2 transition-colors"
                  style={{
                    border: `1px dashed ${dragActive ? "var(--accent)" : "var(--border)"}`,
                    background: dragActive ? "var(--accent-subtle)" : "var(--bg-surface)",
                    minHeight: "9rem",
                  }}
                >
                  <p className="text-sm" style={{ color: "var(--text-secondary)" }}>Drop a PDF here</p>
                  <button
                    type="button"
                    onClick={() => sheetInputRef.current?.click()}
                    className="btn btn-secondary btn-sm"
                  >
                    Choose PDF
                  </button>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>Up to 10 MB, 10 pages</p>
                  <input
                    ref={sheetInputRef}
                    type="file"
                    accept="application/pdf,.pdf"
                    aria-label="Upload a call sheet PDF"
                    className="sr-only"
                    tabIndex={-1}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleCallSheet(file);
                    }}
                  />
                </div>
              </div>
            </div>
            {importError && <p className="text-xs" style={{ color: "var(--danger)" }}>{importError}</p>}
            <button
              type="button"
              onClick={handleParse}
              disabled={!pasteText.trim() || parsing}
              className="btn btn-primary"
            >
              {parsing ? "Importing…" : "Import"}
            </button>
          </div>
        )}

        {/* Quick Import — preview */}
        {showPaste && pasteRows && (
          <div className="card mb-6">
            <div className="px-5 py-3 flex items-center justify-between gap-4" style={{ borderBottom: "1px solid var(--border)" }}>
              <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                {pasteRows.length} {pasteRows.length === 1 ? "person" : "people"} found
                {sheetName && <> on <span style={{ color: "var(--text-secondary)" }}>{sheetName}</span></>}
                {" "}— review and edit before importing
              </p>
              <button type="button" onClick={() => { setPasteRows(null); setSheetName(null); }} className="btn btn-ghost btn-sm shrink-0">← Back</button>
            </div>
            {/* A paste is one type, so one table, exactly as before. A call sheet
                is split into its three sections — each with the columns its own
                tab uses — plus a Type column to move anyone the model filed in
                the wrong one, and whether they're already on the Roster. */}
            {sheetName
              ? ROSTER_TYPES.filter((t) => pasteRows.some((r) => r.type === t)).map((t) => (
                  <div key={t}>
                    <p
                      className="px-5 pt-4 pb-2 text-xs font-semibold uppercase tracking-wider"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {TYPE_LABEL[t].tab} · {pasteRows.filter((r) => r.type === t).length}
                    </p>
                    {previewTable(t, true)}
                  </div>
                ))
              : previewTable(activeTab, false)}
            <div className="px-5 py-4 flex items-center gap-3" style={{ borderTop: "1px solid var(--border)" }}>
              <button
                type="button"
                onClick={handleImport}
                disabled={importing || pasteRows.filter((r) => r.name.trim()).length === 0}
                className="btn btn-primary"
              >
                {importing
                  ? "Importing…"
                  : `Import ${pasteRows.filter((r) => r.name.trim()).length} ${pasteRows.filter((r) => r.name.trim()).length === 1 ? "person" : "people"}`}
              </button>
              {importError && <p className="text-xs" style={{ color: "var(--danger)" }}>{importError}</p>}
            </div>
          </div>
        )}

        {roster.length > 4 && (
          <div className="mb-4">
            <input aria-label="Search roster" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name, role, or email…" className="field-input" />
          </div>
        )}

        {loading ? (
          <TableSkeleton columns={5} />
        ) : loadError ? (
          <div className="card px-5 py-4" style={{ borderLeft: "3px solid var(--danger)" }}>
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              Couldn&rsquo;t load your roster
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Nothing has been deleted — the request didn&rsquo;t go through. {loadError}
            </p>
            <button onClick={loadRoster} className="btn btn-secondary btn-sm mt-3">Try again</button>
          </div>
        ) : roster.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {activeTab === "crew"
              ? "No saved crew yet. Add people you work with regularly."
              : activeTab === "talent"
              ? "No saved talent yet. Talent added to any project will appear here automatically."
              : "No saved clients yet."}
          </p>
        ) : filtered.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>No matches for &ldquo;{search}&rdquo;.</p>
        ) : activeTab === "crew" ? (
          <div className="card overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  {/* All six, matching what both the display and edit rows
                      actually render. This header declared four while the edit
                      row rendered six, so the browser crammed six inputs into
                      four columns of space and truncated every one of them. */}
                  <th>Name</th><th>Role</th><th>Department</th><th>Email</th><th>Phone</th><th />
                </tr>
              </thead>
              <tbody>
                {anyHasDepartment
                  ? crewGroups.flatMap(({ label, entries }) => [
                      <tr key={`dept-${label || "none"}`} style={{ background: "var(--bg-surface)" }}>
                        <td
                          colSpan={6}
                          className="text-xs font-semibold uppercase tracking-wider py-2 px-3"
                          style={{ color: "var(--text-muted)" }}
                        >
                          {label || "No Department"}
                        </td>
                      </tr>,
                      ...entries.map((entry) => editingId === entry.id ? crewEditRow(entry) : crewDisplayRow(entry)),
                    ])
                  : filtered.map((entry) => editingId === entry.id ? crewEditRow(entry) : crewDisplayRow(entry))
                }
              </tbody>
            </table>
          </div>
        ) : activeTab === "client" ? (
          <div className="card overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Organization</th><th>Name</th><th>Role</th><th>Email</th><th>Phone</th><th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((entry) =>
                  editingId === entry.id ? (
                    <tr key={entry.id}>
                      <td><input value={editFields.organization} onChange={(e) => setEditFields((f) => ({ ...f, organization: e.target.value }))} placeholder="Agency, Brand…" className="field-input" /></td>
                      <td><input value={editFields.name} onChange={(e) => setEditFields((f) => ({ ...f, name: e.target.value }))} className="field-input" /></td>
                      <td><input value={editFields.role} onChange={(e) => setEditFields((f) => ({ ...f, role: e.target.value }))} className="field-input" /></td>
                      <td><input type="email" value={editFields.email} onChange={(e) => setEditFields((f) => ({ ...f, email: e.target.value }))} className="field-input" /></td>
                      <td><input type="tel" value={editFields.phone} onChange={(e) => setEditFields((f) => ({ ...f, phone: e.target.value }))} className="field-input" /></td>
                      <td className="text-right whitespace-nowrap">
                        <button onClick={() => handleSave(entry.id)} disabled={editSaving} className="btn btn-ghost btn-sm mr-1">{editSaving ? "Saving…" : "Save"}</button>
                        <button onClick={() => setEditingId(null)} className="btn btn-ghost btn-sm">Cancel</button>
                      </td>
                    </tr>
                  ) : (
                    <tr key={entry.id}>
                      <td style={{ color: "var(--text-secondary)" }}>{entry.organization ?? "—"}</td>
                      <td className="font-medium" style={{ color: "var(--text-primary)" }}>{entry.name}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{entry.role ?? "—"}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{entry.email ?? "—"}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{entry.phone ?? "—"}</td>
                      <td className="text-right whitespace-nowrap">
                        <button onClick={() => startEdit(entry)} className="btn btn-ghost btn-sm mr-1" aria-label={`Edit ${entry.name}`}>Edit</button>
                        {confirmRemove === entry.id ? (
                          <>
                            <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm" aria-label={`Confirm removing ${entry.name}`}>Remove {entry.name.split(" ")[0]}?</button>
                            <button onClick={() => setConfirmRemove(null)} className="btn btn-ghost btn-sm" aria-label={`Keep ${entry.name}`}>Cancel</button>
                          </>
                        ) : (
                          <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm" aria-label={`Remove ${entry.name}`}>Remove</button>
                        )}
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="card overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th><th>Role</th><th>Email</th><th>Phone</th><th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((entry) =>
                  editingId === entry.id ? (
                    <Fragment key={entry.id}>
                    <tr>
                      <td><input value={editFields.name} onChange={(e) => setEditFields((f) => ({ ...f, name: e.target.value }))} className="field-input" /></td>
                      <td><input value={editFields.role} onChange={(e) => setEditFields((f) => ({ ...f, role: e.target.value }))} className="field-input" /></td>
                      <td><input type="email" value={editFields.email} onChange={(e) => setEditFields((f) => ({ ...f, email: e.target.value }))} className="field-input" /></td>
                      <td><input type="tel" value={editFields.phone} onChange={(e) => setEditFields((f) => ({ ...f, phone: e.target.value }))} className="field-input" /></td>
                      <td className="text-right whitespace-nowrap">
                        <button onClick={() => handleSave(entry.id)} disabled={editSaving} className="btn btn-ghost btn-sm mr-1">{editSaving ? "Saving…" : "Save"}</button>
                        <button onClick={() => setEditingId(null)} className="btn btn-ghost btn-sm">Cancel</button>
                      </td>
                    </tr>
                    {/* Rate and agency stay out of the table itself — see the
                        same note on the crew tab's edit row. */}
                    <tr style={{ background: "var(--bg-elevated)" }}>
                      <td colSpan={5} className="px-3 pb-3 space-y-3">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div><label className="field-label">Day rate</label><input aria-label="Day rate" value={editFields.dayRate} onChange={(e) => setEditFields((f) => ({ ...f, dayRate: e.target.value }))} className="field-input" /></div>
                          <div><label className="field-label">Rate note</label><textarea aria-label="Rate note" rows={2} value={editFields.rateNote} onChange={(e) => setEditFields((f) => ({ ...f, rateNote: e.target.value }))} placeholder={"Shoot day rate = $800\nTravel day rate = $400"} className="field-input" /></div>
                        </div>
                        <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                          Represented by — not {entry.name}&rsquo;s own contact info
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                          <div><label className="field-label">Agency</label><input aria-label="Agency" value={editFields.agency} onChange={(e) => setEditFields((f) => ({ ...f, agency: e.target.value }))} className="field-input" /></div>
                          <div><label className="field-label">Agent name</label><input aria-label="Agent name" value={editFields.agentName} onChange={(e) => setEditFields((f) => ({ ...f, agentName: e.target.value }))} className="field-input" /></div>
                          <div><label className="field-label">Agent email</label><input type="email" aria-label="Agent email" value={editFields.agentEmail} onChange={(e) => setEditFields((f) => ({ ...f, agentEmail: e.target.value }))} className="field-input" /></div>
                          <div><label className="field-label">Agent phone</label><input type="tel" aria-label="Agent phone" value={editFields.agentPhone} onChange={(e) => setEditFields((f) => ({ ...f, agentPhone: e.target.value }))} className="field-input" /></div>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                          <div><label className="field-label">Based</label><input aria-label="Based" value={editFields.based} onChange={(e) => setEditFields((f) => ({ ...f, based: e.target.value }))} placeholder="Seattle" className="field-input" /></div>
                          <div className="sm:col-span-3"><label className="field-label">Portfolio link</label><input type="url" aria-label="Portfolio link" value={editFields.portfolioUrl} onChange={(e) => setEditFields((f) => ({ ...f, portfolioUrl: e.target.value }))} placeholder="https://" className="field-input" /></div>
                        </div>
                      </td>
                    </tr>
                    </Fragment>
                  ) : (
                    <tr key={entry.id}>
                      <td className="font-medium" style={{ color: "var(--text-primary)" }}>{entry.name}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{entry.role ?? "—"}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{entry.email ?? "—"}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{entry.phone ?? "—"}</td>
                      <td className="text-right whitespace-nowrap">
                        <button onClick={() => startEdit(entry)} className="btn btn-ghost btn-sm mr-1" aria-label={`Edit ${entry.name}`}>Edit</button>
                        {confirmRemove === entry.id ? (
                          <>
                            <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm" aria-label={`Confirm removing ${entry.name}`}>Remove {entry.name.split(" ")[0]}?</button>
                            <button onClick={() => setConfirmRemove(null)} className="btn btn-ghost btn-sm" aria-label={`Keep ${entry.name}`}>Cancel</button>
                          </>
                        ) : (
                          <button onClick={() => handleRemove(entry.id)} className="btn btn-danger btn-sm" aria-label={`Remove ${entry.name}`}>Remove</button>
                        )}
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
        )}
      </main>
      <AppFooter />
    </div>
  );
}
