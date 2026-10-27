"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, downloadFile, SLOW_TIMEOUT_MS } from "@/lib/api";
import { TimeInput } from "@/components/TimeInput";
import { createClient } from "@/lib/supabase";
import { TERMS_VERSION } from "@/lib/terms";
import { cleanDisplayName, NAME_MAX } from "@/lib/displayName";
import { TitleCard } from "@/components/TitleCard";
import { useBrand } from "@/components/BrandTheme";

interface CallSheet {
  id: string;
  html_content: string;
  generated_at: string;
  sent_at: string | null;
}

interface CrewMember {
  id: string;
  name: string;
  role: string | null;
  call_time: string | null;
  confirmed_at: string | null;
  email: string | null;
  last_sent_at: string | null;
}

interface TextNudge {
  crew_id: string;
  phone: string;
  message: string;
}

interface Contact {
  id: string;
  name: string;
  organization: string | null;
  role: string | null;
  email: string | null;
  last_sent_at: string | null;
}

interface Project {
  id: string;
  name: string;
  shoot_date: string | null;
  first_call_time: string | null;
  first_shot_time: string | null;
  lunch_time: string | null;
  est_wrap_time: string | null;
}

interface ScheduleItem {
  end_time: string | null;
}

interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  original_byte_size: number;
}

// Matches the backend's human_size, so the producer sees one number for a file
// whichever side of the wire reports it.
function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// The pills across the head of the sheet, in the fixed chronological order a
// call sheet reads. Blank hides a pill — that's the whole mechanism, so there's
// no toggle to keep in sync with the value.
const HEADER_TIME_FIELDS = [
  { key: "first_call_time", label: "First call" },
  { key: "first_shot_time", label: "First shot" },
  { key: "lunch_time", label: "Lunch" },
  { key: "est_wrap_time", label: "Est. wrap" },
] as const;

type HeaderTimeKey = (typeof HEADER_TIME_FIELDS)[number]["key"];

const EMPTY_HEADER_TIMES: Record<HeaderTimeKey, string> = {
  first_call_time: "",
  first_shot_time: "",
  lunch_time: "",
  est_wrap_time: "",
};

interface Summary {
  crew_count: number;
  crew_missing_call_time: number;
  contact_count: number;
  schedule_item_count: number;
  has_location: boolean;
}

function fmt(t: string) {
  const [h, m] = t.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${ampm}`;
}

function initials(name: string) {
  return name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
}

// iOS wants sms:number&body=, everything else wants sms:number?body=. Getting
// this wrong opens Messages with an empty draft, which looks like the button
// silently failed. Strip formatting from the number so "(310) 555-0134" dials.
function smsHref(phone: string, message: string) {
  const number = phone.replace(/[^\d+]/g, "");
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  const sep = /iPad|iPhone|iPod/.test(ua) ? "&" : "?";
  return `sms:${number}${sep}body=${encodeURIComponent(message)}`;
}

// Defensive trim for older sheets whose stored HTML has a stray leading title
// line (e.g. "Call Sheet – {name}") before the first tag — keep only the markup
// so it never shows as bare text in the preview or downloaded PDF.
function cleanSheetHtml(htmlStr: string): string {
  const start = htmlStr.indexOf("<");
  const end = htmlStr.lastIndexOf(">");
  return start >= 0 && end > start ? htmlStr.slice(start, end + 1) : htmlStr;
}

const STATUS_MESSAGES = [
  "Gathering crew and schedule data…",
  "Composing call sheet sections…",
  "Formatting location and maps…",
  "Reviewing layout…",
];

// Once the functional steps are done and generation is in its final stretch,
// cycle these on a loop so the wait never looks frozen.
const FUN_MESSAGES = [
  "Still going — good time to put the kettle on ☕",
  "Hang tight — maybe take the dog out 🐕",
  "Touch some grass in the meantime 🌱",
  "Stretch your legs — we'll keep composing",
  "Refill the coffee… almost there",
  "Lining up call times so no one shows up at 5 AM by mistake ⏰",
  "Making it look effortless — it never is ✨",
  "Lights, camera, formatting 🎬",
  "Herding the crew list into tidy little rows 🐈",
  "Double-checking the schedule so you don't have to 📋",
  "Good things take a beat — like a perfect take 🎯",
  "Tightening the margins so it prints clean 🖨️",
  "Almost in the can — hang tight 🎞️",
  "Mapping parking so nobody circles the block 🅿️",
  "Smoothing the edges — this is the fun part for us 🛠️",
  "Quietly judging your 6 AM call time (respect) 🫡",
  "One more polish pass and we're wrapped 🎬",
];

// Fisher–Yates — used to randomize the fun-message order each generation so
// they don't always appear in the same sequence.
function shuffled<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export default function CallSheetPage() {
  const { id } = useParams<{ id: string }>();
  const [sheet, setSheet] = useState<CallSheet | null>(null);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const msgIndexRef = useRef(0);
  const funQueueRef = useRef<string[]>([]);
  const lastFunRef = useRef("");
  const sheetContainerRef = useRef<HTMLDivElement>(null);
  // Set when a generate succeeds so the effect below scrolls the finished sheet
  // into view once — but never on initial load of an already-generated sheet.
  const justGeneratedRef = useRef(false);
  const [sheetZoom, setSheetZoom] = useState(1);
  const [sending, setSending] = useState(false);
  const [updateNote, setUpdateNote] = useState("");
  const [showUpdatePanel, setShowUpdatePanel] = useState(false);
  const [showSendConfirm, setShowSendConfirm] = useState(false);
  const [senderName, setSenderName] = useState<string | null>(null);
  const [editingSender, setEditingSender] = useState(false);
  const [draftSender, setDraftSender] = useState("");
  const [savingSender, setSavingSender] = useState(false);
  const [error, setError] = useState("");
  const [sendResult, setSendResult] = useState("");
  const [remindingId, setRemindingId] = useState<string | null>(null);
  const [remindedIds, setRemindedIds] = useState<Set<string>>(new Set());
  // Pre-written confirm texts, keyed by crew id. Fetched up front rather than
  // on click so tapping "Text" is a plain link navigation — an async fetch
  // first would put the sms: hop outside the user gesture, which mobile
  // browsers block. Only crew with a phone number appear here.
  const [nudges, setNudges] = useState<Record<string, TextNudge>>({});
  const [textedIds, setTextedIds] = useState<Set<string>>(new Set());
  const [copiedId, setCopiedId] = useState<string | null>(null);
  // Phones get the sms: link; desktop gets copy-to-clipboard, since sms: is a
  // dead end on most desktop browsers. Set after mount — navigator isn't there
  // during the server render.
  const [onPhone, setOnPhone] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  // Who the next send goes to. Seeded when the dialog opens, not on load, so it
  // always reflects who still needs the sheet at that moment.
  const [pickedCrew, setPickedCrew] = useState<Set<string>>(new Set());
  const [pickedContacts, setPickedContacts] = useState<Set<string>>(new Set());
  const [crew, setCrew] = useState<CrewMember[]>([]);
  const [loadingCrew, setLoadingCrew] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const brand = useBrand();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [times, setTimes] = useState<Record<HeaderTimeKey, string>>(EMPTY_HEADER_TIMES);
  const [savingTime, setSavingTime] = useState<HeaderTimeKey | null>(null);
  const [savedTime, setSavedTime] = useState<HeaderTimeKey | null>(null);
  const [timeError, setTimeError] = useState("");
  const [schedule, setSchedule] = useState<ScheduleItem[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [attachError, setAttachError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  // null = not yet loaded; true/false = whether this user has acknowledged the
  // beta notice before. Stored in Supabase user metadata so it's one-time.
  const [betaAck, setBetaAck] = useState<boolean | null>(null);
  const [showBetaModal, setShowBetaModal] = useState(false);
  const [acking, setAcking] = useState(false);

  useEffect(() => {
    api.get<CallSheet>(`/api/projects/${id}/call-sheet`).then(setSheet).catch(() => {});
    api.get<Project>(`/api/projects/${id}`)
      .then((p) => {
        setProject(p);
        setTimes({
          first_call_time: p.first_call_time ? fmt(p.first_call_time) : "",
          first_shot_time: p.first_shot_time ? fmt(p.first_shot_time) : "",
          lunch_time: p.lunch_time ? fmt(p.lunch_time) : "",
          est_wrap_time: p.est_wrap_time ? fmt(p.est_wrap_time) : "",
        });
      })
      .catch(() => {});
    // Only for the est-wrap suggestion below — the sheet's schedule section is
    // rendered from the backend's own fetch, not from this.
    api.get<ScheduleItem[]>(`/api/projects/${id}/schedule`).then(setSchedule).catch(() => {});
    api.get<Attachment[]>(`/api/projects/${id}/attachments`).then(setAttachments).catch(() => {});
    api.get<Summary>(`/api/projects/${id}/summary`).then(setSummary).catch(() => {});
    api.get<Contact[]>(`/api/projects/${id}/contacts`).then(setContacts).catch(() => {});
  }, [id]);

  useEffect(() => {
    setOnPhone(/iPad|iPhone|iPod|Android/.test(navigator.userAgent));
  }, []);

  useEffect(() => {
    createClient()
      .auth.getUser()
      .then(({ data }) => {
        setBetaAck(!!data.user?.user_metadata?.callsheet_beta_ack_at);
        // Same order the backend uses: full_name, then company for accounts
        // seeded before there was any UI for a name.
        const meta = data.user?.user_metadata ?? {};
        setSenderName(cleanDisplayName((meta.full_name as string) || (meta.company as string)));
      })
      .catch(() => setBetaAck(false));
  }, []);

  /* Saving the producer's own name from inside the send dialog.
   *
   * It lives here rather than only on the account page because this is the
   * moment it matters and the only moment anyone thinks about it — the account
   * page is a link in a header nobody visits, so a setting parked there is a
   * setting that does not exist. Right before a call sheet goes to fifteen
   * people is exactly when "who does this come from" is a live question. */
  async function saveSenderName() {
    const cleaned = cleanDisplayName(draftSender);
    setSavingSender(true);
    try {
      const { error } = await createClient().auth.updateUser({ data: { full_name: cleaned ?? "" } });
      if (error) throw new Error(error.message);
      setSenderName(cleaned);
      setEditingSender(false);
    } catch {
      // Deliberately quiet: this is a courtesy control inside a dialog whose job
      // is sending. A failure here must not look like the send failed, and the
      // send is unaffected — it just goes out under the previous name.
      setEditingSender(false);
    } finally {
      setSavingSender(false);
    }
  }

  useEffect(() => {
    if (!sheet) return;
    function updateZoom() {
      if (!sheetContainerRef.current) return;
      const w = sheetContainerRef.current.offsetWidth;
      setSheetZoom(Math.min(1, w / 690));
    }
    const t = setTimeout(updateZoom, 50);
    window.addEventListener("resize", updateZoom);
    return () => { clearTimeout(t); window.removeEventListener("resize", updateZoom); };
  }, [sheet]);

  // Bring a freshly generated sheet into view. Generate and "Send to crew" sit
  // together in the header row, so a producer who doesn't scroll can send a
  // sheet they never actually looked at — which is exactly how placeholder text
  // reached a crew of 15. Runs only after a generate, not on page load.
  useEffect(() => {
    if (generating || !sheet || !justGeneratedRef.current) return;
    justGeneratedRef.current = false;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const t = setTimeout(() => {
      sheetContainerRef.current?.scrollIntoView({
        behavior: reduce ? "auto" : "smooth",
        block: "nearest",
      });
    }, 80);
    return () => clearTimeout(t);
  }, [generating, sheet]);

  const refreshCrew = useCallback(() => {
    setLoadingCrew(true);
    api.get<CrewMember[]>(`/api/projects/${id}/crew`)
      .then(setCrew).catch(console.error).finally(() => setLoadingCrew(false));
  }, [id]);

  useEffect(() => { refreshCrew(); }, [refreshCrew]);

  // Only meaningful once the sheet has gone out — the backend returns nothing
  // before that, since there's nothing yet to confirm receipt of.
  useEffect(() => {
    if (!sheet?.sent_at) return;
    api.get<TextNudge[]>(`/api/projects/${id}/call-sheet/text-nudges`)
      .then((list) => setNudges(Object.fromEntries(list.map((n) => [n.crew_id, n]))))
      .catch(() => {});
  }, [id, sheet?.sent_at]);

  function startProgress() {
    setProgress(0);
    msgIndexRef.current = 0;
    funQueueRef.current = [];
    lastFunRef.current = "";
    setStatusMsg(STATUS_MESSAGES[0]);
    progressRef.current = setInterval(() => {
      setProgress((p) => Math.min(p + 1.5, 90));
    }, 400);
    statusRef.current = setInterval(() => {
      const i = (msgIndexRef.current += 1);
      if (i < STATUS_MESSAGES.length) {
        setStatusMsg(STATUS_MESSAGES[i]);
      } else {
        // Past the functional steps — draw fun messages from a shuffled queue so
        // they appear in a random order. Refill (reshuffle) when the queue empties,
        // avoiding the same line twice in a row across the refill boundary.
        if (funQueueRef.current.length === 0) {
          const next = shuffled(FUN_MESSAGES);
          if (next.length > 1 && next[0] === lastFunRef.current) {
            [next[0], next[1]] = [next[1], next[0]];
          }
          funQueueRef.current = next;
        }
        const msg = funQueueRef.current.shift()!;
        lastFunRef.current = msg;
        setStatusMsg(msg);
      }
    }, 5000);
  }

  function finishProgress() {
    if (progressRef.current) clearInterval(progressRef.current);
    if (statusRef.current) clearInterval(statusRef.current);
    setStatusMsg("");
    setProgress(100);
    setTimeout(() => setProgress(0), 600);
  }

  function cancelGenerate() {
    abortRef.current?.abort();
    if (progressRef.current) clearInterval(progressRef.current);
    if (statusRef.current) clearInterval(statusRef.current);
    setProgress(0);
    setStatusMsg("");
    setGenerating(false);
  }

  // Saved on blur rather than behind a Save button: the producer's next move is
  // Refresh Call Sheet, and a pill silently missing because an edit was never
  // committed is the same class of bug this whole feature exists to fix.
  // `raw` lets a suggestion save the value it just set, before state flushes.
  async function saveHeaderTime(key: HeaderTimeKey, raw?: string) {
    const value = (raw ?? times[key]).trim();
    const stored = project?.[key] ?? null;
    // Empty and unset, or unchanged — don't write on every tab-through.
    if (!value && !stored) return;
    if (value && stored && fmt(stored) === value) return;

    setSavingTime(key);
    setTimeError("");
    try {
      const updated = await api.put<Project>(`/api/projects/${id}`, { [key]: value || null });
      setProject(updated);
      setTimes((t) => ({ ...t, [key]: updated[key] ? fmt(updated[key]!) : "" }));
      setSavedTime(key);
      setTimeout(() => setSavedTime((k) => (k === key ? null : k)), 1500);
    } catch (err) {
      // Put the field back to what's actually stored, so what's on screen is
      // never a time the sheet won't print.
      setTimes((t) => ({ ...t, [key]: stored ? fmt(stored) : "" }));
      // fetch reports a network/CORS failure as a bare TypeError "Failed to
      // fetch" — true, and useless to a producer mid-prep. Say what it means.
      setTimeError(
        err instanceof TypeError
          ? "Couldn't reach the server — check your connection and try again."
          : err instanceof Error ? err.message : "Couldn't save that time"
      );
    } finally {
      setSavingTime(null);
    }
  }

  async function handleUploadAttachment(file: File) {
    setUploading(true);
    setAttachError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const created = await api.upload<Attachment>(`/api/projects/${id}/attachments`, form);
      setAttachments((list) => [...list, created]);
    } catch (err) {
      setAttachError(err instanceof Error ? err.message : "Couldn't upload that file");
    } finally {
      setUploading(false);
      // Clear the picker so re-choosing the same file still fires a change.
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleRemoveAttachment(attachmentId: string) {
    setAttachError("");
    try {
      await api.delete(`/api/projects/${id}/attachments/${attachmentId}`);
      setAttachments((list) => list.filter((a) => a.id !== attachmentId));
    } catch (err) {
      setAttachError(err instanceof Error ? err.message : "Couldn't remove that file");
    }
  }

  function applySuggestion(key: HeaderTimeKey, stored: string) {
    const display = fmt(stored);
    setTimes((t) => ({ ...t, [key]: display }));
    saveHeaderTime(key, display);
  }

  // Gate the first generation behind a one-time beta acknowledgment. Once the
  // user has accepted (recorded in their metadata), this passes straight through.
  function handleGenerate() {
    if (betaAck === false) {
      setShowBetaModal(true);
      return;
    }
    runGenerate();
  }

  async function acceptBetaAndGenerate() {
    setAcking(true);
    try {
      await createClient().auth.updateUser({
        data: {
          callsheet_beta_ack_at: new Date().toISOString(),
          callsheet_beta_ack_version: TERMS_VERSION,
        },
      });
      setBetaAck(true);
    } catch {
      // Recording is best-effort — don't block generation on a metadata write.
    } finally {
      setAcking(false);
      setShowBetaModal(false);
    }
    runGenerate();
  }

  async function runGenerate() {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setGenerating(true);
    setError("");
    startProgress();
    try {
      const result = await api.post<CallSheet>(`/api/projects/${id}/call-sheet/generate`, {}, { signal: ctrl.signal, timeoutMs: SLOW_TIMEOUT_MS });
      finishProgress();
      justGeneratedRef.current = true;
      setSheet(result);
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      if (progressRef.current) clearInterval(progressRef.current);
      setProgress(0);
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }

  // Rendered by the API, not by the browser. This used to open a window and
  // call window.print(), which handed the result to whichever export the user
  // picked in Chrome's dialog — and both macOS routes re-render through Quartz
  // and throw away hyperlink annotations, so the Apple Maps and Google Maps
  // buttons came out painted on and dead. No dialog, no settings to get wrong,
  // and the file the producer downloads is now the same one the crew are sent.
  async function handleDownloadPDF() {
    if (!sheet) return;
    setDownloading(true);
    setError("");
    try {
      const { blob, filename } = await downloadFile(`/api/projects/${id}/call-sheet/pdf`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename ?? "Call Sheet.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not download the PDF");
    } finally {
      setDownloading(false);
    }
  }

  // Escape backs out of the send confirmation — never while a send is already
  // in flight, since closing then would imply it was cancelled when it wasn't.
  useEffect(() => {
    if (!showSendConfirm) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !sending) setShowSendConfirm(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showSendConfirm, sending]);

  // Crew without an email address can't be mailed, and the backend builds each
  // message straight from the address — so a blank one is worth surfacing
  // before the send rather than after it.
  const crewWithEmail = crew.filter((m) => (m.email ?? "").trim() !== "");
  const crewMissingEmail = crew.length - crewWithEmail.length;
  const contactCount = summary?.contact_count ?? 0;
  const contactsWithEmail = contacts.filter((c) => (c.email ?? "").trim() !== "");

  // "Already has it" means sent AFTER this sheet was generated. Regenerating
  // makes everyone unsent again, because what they received is no longer the
  // sheet that exists — which is exactly the review loop: send to one person,
  // act on their notes, regenerate, and the whole unit is queued up again.
  const hasCurrentSheet = (sentAt: string | null) =>
    !!sentAt && !!sheet && new Date(sentAt) > new Date(sheet.generated_at);

  const crewPending = crewWithEmail.filter((m) => !hasCurrentSheet(m.last_sent_at));
  const contactsPending = contactsWithEmail.filter((c) => !hasCurrentSheet(c.last_sent_at));
  const totalRecipients = crewWithEmail.length + contactsWithEmail.length;
  // Guarded on there being anyone at all, or a project with no addressable
  // recipients would read as "everyone already has it".
  const everyoneHasCurrent =
    totalRecipients > 0 && crewPending.length === 0 && contactsPending.length === 0;

  function openSendDialog() {
    // Default to whoever still needs it. On a first send that's everyone; after
    // a review send it's precisely the people left.
    const seedCrew = crewPending.length ? crewPending : crewWithEmail;
    const seedContacts = contactsPending.length ? contactsPending : contactsWithEmail;
    setPickedCrew(new Set(seedCrew.map((m) => m.id)));
    setPickedContacts(new Set(seedContacts.map((c) => c.id)));
    setShowSendConfirm(true);
  }

  const pickedCount = pickedCrew.size + pickedContacts.size;

  function toggleIn(set: Set<string>, id: string) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  }

  /**
   * `picked` present = the recipient dialog chose who. Absent = the update
   * panel, which has always gone to everyone and still does; omitting the ids
   * entirely is what the API reads as "the whole unit", so a stale selection
   * from an earlier dialog can never leak into an update.
   */
  async function handleSend(picked?: { crew: string[]; contacts: string[] }) {
    setShowSendConfirm(false);
    setSending(true); setError(""); setSendResult("");
    try {
      const result = await api.post<{ sent_to: number }>(`/api/projects/${id}/call-sheet/send`, {
        update_note: updateNote.trim() || null,
        crew_ids: picked ? picked.crew : null,
        contact_ids: picked ? picked.contacts : null,
      }, { timeoutMs: SLOW_TIMEOUT_MS });
      setSendResult(`Call sheet sent to ${result.sent_to} ${result.sent_to === 1 ? "person" : "people"}.`);
      setSheet((prev) => prev ? { ...prev, sent_at: new Date().toISOString() } : prev);
      setUpdateNote("");
      setShowUpdatePanel(false);
      refreshCrew();
      // Contacts carry last_sent_at too — without this the picker would still
      // show them as pending after they've just been sent to.
      api.get<Contact[]>(`/api/projects/${id}/contacts`).then(setContacts).catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally { setSending(false); }
  }

  // Nudge one crew member who hasn't confirmed. Sends the same stored sheet they
  // already received, so a reminder never carries different information than the
  // rest of the unit got.
  async function handleRemind(member: CrewMember) {
    setRemindingId(member.id);
    setError(""); setSendResult("");
    try {
      await api.post(`/api/projects/${id}/call-sheet/remind/${member.id}`, {});
      setRemindedIds((prev) => new Set(prev).add(member.id));
      setSendResult(`Reminder sent to ${member.name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reminder failed");
    } finally { setRemindingId(null); }
  }

  // Desktop path: put the text on the clipboard so it can be pasted into
  // whatever the producer texts from. Nothing is sent from here either way.
  async function handleCopyText(member: CrewMember, nudge: TextNudge) {
    try {
      await navigator.clipboard.writeText(nudge.message);
      setCopiedId(member.id);
      setTextedIds((prev) => new Set(prev).add(member.id));
      setTimeout(() => setCopiedId((cur) => (cur === member.id ? null : cur)), 2000);
    } catch {
      setError("Couldn't copy the message — your browser blocked clipboard access.");
    }
  }

  const checks = project && summary ? [
    { label: "Shoot date", ok: !!project.shoot_date, detail: project.shoot_date ? new Date(project.shoot_date + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }) : null, fix: `/projects/${id}`, fixLabel: "Set date" },
    { label: "Crew", ok: summary.crew_count > 0, detail: summary.crew_count > 0 ? `${summary.crew_count} member${summary.crew_count === 1 ? "" : "s"}` : null, fix: `/projects/${id}/crew`, fixLabel: "Add crew" },
    { label: "Location", ok: summary.has_location, detail: summary.has_location ? "Address set" : null, fix: `/projects/${id}/location`, fixLabel: "Add location" },
    { label: "Schedule", ok: summary.schedule_item_count > 0, detail: summary.schedule_item_count > 0 ? `${summary.schedule_item_count} item${summary.schedule_item_count === 1 ? "" : "s"}` : null, fix: `/projects/${id}/schedule`, fixLabel: "Build schedule" },
  ] : [];

  // Offered, never applied on its own. The header used to derive these times and
  // publish them unasked — a producer found a LUNCH pill on a sheet already sent
  // to crew. A suggestion she has to press keeps the convenience without putting
  // a number in front of a crew that nobody chose.
  const headerSuggestions: Partial<Record<HeaderTimeKey, string>> = {};
  const earliestCall = crew.map((m) => m.call_time).filter((t): t is string => !!t).sort()[0];
  if (earliestCall) headerSuggestions.first_call_time = earliestCall;
  const latestEnd = schedule.map((s) => s.end_time).filter((t): t is string => !!t).sort().pop();
  if (latestEnd) headerSuggestions.est_wrap_time = latestEnd;

  const allClear = checks.length > 0 && checks.every((c) => c.ok);
  const noCallTimeCount = summary?.crew_missing_call_time ?? 0;
  const confirmed = crew.filter((m) => m.confirmed_at);
  // Derived from the people, not from the current sheet revision. Generating
  // replaces the stored call_sheets row, so sheet.sent_at resets to null the
  // moment a producer refreshes an already-sent sheet — which used to take the
  // whole confirmation tracker with it and read as "everyone's confirmation
  // vanished". Whether someone confirmed is a fact about that person, and it
  // outlives any number of redrafts. It also has to outlive the shoot: weeks
  // later, "their call sheet says confirmed" is the answer to why somebody
  // says they never knew.
  const lastSentAt = [...crew, ...contacts]
    .map((p) => p.last_sent_at)
    .filter((t): t is string => !!t)
    .sort()
    .pop() ?? null;
  const hasSent = !!lastSentAt || confirmed.length > 0;

  return (
    <div className="max-w-5xl mx-auto px-4 md:px-8 py-10 space-y-6">
      {/* One-time beta acknowledgment — shown before the first generation, then
          recorded so it never appears again for this user. */}
      {showBetaModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "var(--scrim)" }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="beta-modal-title"
        >
          <div className="card p-6 w-full max-w-md">
            <h3 id="beta-modal-title" className="text-base font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              One thing before you generate
            </h3>
            <div className="space-y-3 text-sm" style={{ color: "var(--text-secondary)" }}>
              <p>
                SET&gt;READY is in <strong style={{ color: "var(--text-primary)" }}>early beta</strong>, and call
                sheets are generated automatically. They can contain mistakes.
              </p>
              <p>
                <strong style={{ color: "var(--text-primary)" }}>Review every detail</strong> — call times,
                addresses, and names — before you send. You&rsquo;re responsible for the final call sheet you
                distribute to your crew. The Service is provided &ldquo;as is,&rdquo; without warranties, during beta.
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                Full details in our{" "}
                <Link href="/terms" target="_blank" className="font-medium" style={{ color: "var(--accent-hover)" }}>Terms</Link>.
              </p>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setShowBetaModal(false)} disabled={acking} className="btn btn-ghost">
                Cancel
              </button>
              <button onClick={acceptBetaAndGenerate} disabled={acking} className="btn btn-primary">
                {acking ? "One sec…" : "I understand — generate"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Send confirmation — the last stop before a sheet reaches real crew.
          Email can't be recalled, so state plainly who it's going to and give
          an obvious way back to the preview. */}
      {showSendConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "var(--scrim)" }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="send-confirm-title"
        >
          <div className="card p-6 w-full max-w-md">
            <h3 id="send-confirm-title" className="text-base font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              Send this call sheet?
            </h3>
            <div className="space-y-3 text-sm" style={{ color: "var(--text-secondary)" }}>
              <p>
                It goes to{" "}
                <strong style={{ color: "var(--text-primary)" }}>
                  {pickedCount} {pickedCount === 1 ? "person" : "people"}
                </strong>{" "}
                of {crewWithEmail.length + contactsWithEmail.length}. Email can&rsquo;t be unsent.
              </p>

              {/* Who it comes from, at the moment that question is live. An
                  unset name means crew get mail from a brand they have never
                  heard of instead of the person who hired them. */}
              {!editingSender ? (
                <p>
                  They see it from{" "}
                  <strong style={{ color: "var(--text-primary)" }}>
                    {senderName ? `${senderName} via Set Ready` : "Set Ready"}
                  </strong>
                  {senderName ? ". " : " \u2014 they may not recognise that. "}
                  <button
                    type="button"
                    onClick={() => { setDraftSender(senderName ?? ""); setEditingSender(true); }}
                    className="underline"
                    style={{ color: "var(--accent-text)", background: "none", border: "none", padding: 0, cursor: "pointer", font: "inherit" }}
                  >
                    {senderName ? "Change" : "Add your name"}
                  </button>
                </p>
              ) : (
                <div className="space-y-2">
                  <label htmlFor="sender-name" className="field-label">
                    The name your crew knows you by
                  </label>
                  <input
                    id="sender-name"
                    type="text"
                    value={draftSender}
                    maxLength={NAME_MAX}
                    placeholder="Pat Kehoe"
                    autoFocus
                    onChange={(e) => setDraftSender(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); saveSenderName(); }
                      // Escape closes the editor, not the whole dialog — losing a
                      // half-typed name AND the send would be its own small
                      // betrayal.
                      if (e.key === "Escape") { e.stopPropagation(); setEditingSender(false); }
                    }}
                    className="field-input"
                    autoComplete="name"
                  />
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                    They see it from{" "}
                    <strong style={{ color: "var(--text-secondary)" }}>
                      {cleanDisplayName(draftSender)
                        ? `${cleanDisplayName(draftSender)} via Set Ready`
                        : "Set Ready"}
                    </strong>
                  </p>
                  <div className="flex items-center gap-3">
                    <button type="button" onClick={saveSenderName} disabled={savingSender} className="btn btn-primary btn-sm">
                      {savingSender ? "Saving\u2026" : "Save"}
                    </button>
                    <button type="button" onClick={() => setEditingSender(false)} className="btn btn-ghost btn-sm">
                      Cancel
                    </button>
                  </div>
                </div>
              )}
              <p>
                If you haven&rsquo;t read it over yet, go back and check{" "}
                <strong style={{ color: "var(--text-primary)" }}>the date, the address, and call times</strong>{" "}
                &mdash; that&rsquo;s what crew act on.
              </p>
              {crewMissingEmail > 0 && (
                <p className="text-xs" style={{ color: "var(--danger)" }}>
                  ⚠ {crewMissingEmail} {crewMissingEmail === 1 ? "crew member has" : "crew members have"} no email
                  address and won&rsquo;t receive this.
                </p>
              )}
              {/* Named here because they go out to everyone and can't be
                  recalled either — the same reason the recipient list is shown. */}
              {attachments.length > 0 && (
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Attached: {attachments.map((a) => a.filename).join(", ")}
                </p>
              )}
            </div>

            {/* Recipient picker — send to one or two people for review first,
                then come back and send to the rest. */}
            <div className="mt-4 rounded-lg" style={{ border: "1px solid var(--border)" }}>
              <div className="flex items-center justify-between px-3 py-2" style={{ borderBottom: "1px solid var(--border)" }}>
                <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                  Who gets it
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      setPickedCrew(new Set(crewWithEmail.map((m) => m.id)));
                      setPickedContacts(new Set(contactsWithEmail.map((c) => c.id)));
                    }}
                    className="text-xs"
                    style={{ color: "var(--accent-hover)" }}
                  >
                    Everyone
                  </button>
                  <span className="text-xs" style={{ color: "var(--border)" }}>|</span>
                  <button
                    onClick={() => { setPickedCrew(new Set()); setPickedContacts(new Set()); }}
                    className="text-xs"
                    style={{ color: "var(--text-muted)" }}
                  >
                    None
                  </button>
                </div>
              </div>
              <div className="max-h-56 overflow-y-auto px-3 py-2 space-y-1">
                {crewWithEmail.map((m) => (
                  <label key={m.id} className="flex items-center gap-2 py-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={pickedCrew.has(m.id)}
                      onChange={() => setPickedCrew((prev) => toggleIn(prev, m.id))}
                    />
                    <span className="text-sm flex-1 truncate" style={{ color: "var(--text-primary)" }}>
                      {m.name}
                      {m.role && <span className="text-xs ml-1" style={{ color: "var(--text-muted)" }}>{m.role}</span>}
                    </span>
                    {hasCurrentSheet(m.last_sent_at) && (
                      <span className="text-[10px] shrink-0" style={{ color: "var(--text-muted)" }}>already sent</span>
                    )}
                  </label>
                ))}
                {contactsWithEmail.length > 0 && (
                  <p className="text-[10px] uppercase tracking-wide pt-2" style={{ color: "var(--text-muted)" }}>Agency &amp; client</p>
                )}
                {contactsWithEmail.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 py-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={pickedContacts.has(c.id)}
                      onChange={() => setPickedContacts((prev) => toggleIn(prev, c.id))}
                    />
                    <span className="text-sm flex-1 truncate" style={{ color: "var(--text-primary)" }}>
                      {c.name}
                      {c.organization && <span className="text-xs ml-1" style={{ color: "var(--text-muted)" }}>{c.organization}</span>}
                    </span>
                    {hasCurrentSheet(c.last_sent_at) && (
                      <span className="text-[10px] shrink-0" style={{ color: "var(--text-muted)" }}>already sent</span>
                    )}
                  </label>
                ))}
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setShowSendConfirm(false)} disabled={sending} className="btn btn-ghost">
                Back to preview
              </button>
              <button
                onClick={() => handleSend({ crew: [...pickedCrew], contacts: [...pickedContacts] })}
                disabled={sending || pickedCount === 0}
                className="btn btn-primary"
              >
                {sending ? "Sending…" : pickedCount === 0 ? "Select someone" : `Send to ${pickedCount}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header row */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Call Sheet</h2>
          {/* From the recipients too, for the same reason — a refresh resets the
              sheet's own sent_at and this line would disappear mid-job. */}
          {lastSentAt && (
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              Last sent {new Date(lastSentAt).toLocaleString()}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          {generating ? (
            <button onClick={cancelGenerate} className="btn btn-secondary">Cancel</button>
          ) : (
            <>
              <button onClick={handleGenerate} className="btn btn-primary">
                {sheet ? "Refresh Call Sheet" : "Preview Call Sheet"}
              </button>
              {/* Keyed on who still needs THIS sheet, not on whether the sheet
                  has ever been sent. After a review send to one person, the
                  other fifteen are still waiting on a first send — calling that
                  an "update" would be wrong for every one of them. */}
              {sheet && !everyoneHasCurrent && (
                <button onClick={openSendDialog} disabled={sending} className="btn btn-secondary">
                  {sending ? "Sending…" : "Send to crew"}
                </button>
              )}
              {sheet && everyoneHasCurrent && !showUpdatePanel && (
                <button onClick={() => setShowUpdatePanel(true)} className="btn btn-secondary">
                  Send update
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Top line — the pills across the head of the sheet. Producer-set, not
          derived: these were previously inferred from the schedule, which is how
          a LUNCH pill reached a real crew unasked. Blank hides a pill. */}
      <div className="card px-5 py-4">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
            Top line
          </p>
          {savedTime && <span className="text-xs" style={{ color: "var(--success)" }}>Saved</span>}
        </div>
        <p className="text-xs mt-1 mb-3" style={{ color: "var(--text-muted)" }}>
          These show as pills across the top of the call sheet. Leave one blank to hide it.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {HEADER_TIME_FIELDS.map((field) => {
            const suggestion = headerSuggestions[field.key];
            return (
              <div key={field.key}>
                <label className="field-label" htmlFor={`top-line-${field.key}`}>{field.label}</label>
                <TimeInput
                  id={`top-line-${field.key}`}
                  ariaLabel={field.label}
                  value={times[field.key]}
                  onChange={(v) => setTimes((t) => ({ ...t, [field.key]: v }))}
                  onBlur={() => saveHeaderTime(field.key)}
                />
                {!times[field.key] && suggestion && (
                  <button
                    type="button"
                    onClick={() => applySuggestion(field.key, suggestion)}
                    disabled={savingTime === field.key}
                    className="text-xs mt-1"
                    style={{ color: "var(--accent-hover)" }}
                  >
                    Use {fmt(suggestion)}
                  </button>
                )}
              </div>
            );
          })}
        </div>
        {timeError && <p className="text-xs mt-2" style={{ color: "var(--danger)" }}>{timeError}</p>}
        {sheet && (
          <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
            Refresh the call sheet to see these on it.
          </p>
        )}
      </div>

      {/* Attachments — the producer's own files, sent alongside the sheet but
          deliberately never shown on it. A call sheet that carries everything
          gets read for nothing; a set plot belongs beside it, not inside it. */}
      <div className="card px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
          Attachments
        </p>
        <p className="text-xs mt-1 mb-3" style={{ color: "var(--text-muted)" }}>
          Set plots, layout diagrams, anything you made yourself. Sent with the call sheet
          to everyone who receives it — not printed on the sheet. PDFs and images.
        </p>

        {attachments.length > 0 && (
          <ul className="mb-3 space-y-1">
            {attachments.map((file) => (
              <li
                key={file.id}
                className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg"
                style={{ background: "var(--bg-elevated)" }}
              >
                <span className="text-sm truncate" style={{ color: "var(--text-primary)" }}>
                  {file.filename}
                </span>
                <span className="flex items-center gap-3 shrink-0">
                  <span className="text-xs tabular-nums" style={{ color: "var(--text-muted)" }}>
                    {/* Show the trade openly rather than quietly rewriting their file. */}
                    {file.original_byte_size > file.byte_size
                      ? `${fileSize(file.original_byte_size)} → ${fileSize(file.byte_size)}`
                      : fileSize(file.byte_size)}
                  </span>
                  <button
                    onClick={() => handleRemoveAttachment(file.id)}
                    className="text-xs"
                    style={{ color: "var(--danger)" }}
                    aria-label={`Remove ${file.filename}`}
                  >
                    Remove
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf,image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleUploadAttachment(file);
          }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="btn btn-secondary btn-sm"
        >
          {uploading ? "Uploading…" : attachments.length ? "Add another file" : "Add a file"}
        </button>

        {attachError && <p className="text-xs mt-2" style={{ color: "var(--danger)" }}>{attachError}</p>}
      </div>

      {/* Update panel — revealed on demand when re-sending a previously sent sheet */}
      {showUpdatePanel && sheet && !generating && (
        <div className="card px-5 py-4">
          <label className="field-label">What changed? <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(optional)</span></label>
          <input
            aria-label="What changed?"
            value={updateNote}
            onChange={(e) => setUpdateNote(e.target.value)}
            placeholder="e.g. Location updated — new address below"
            className="field-input"
            autoFocus
          />
          <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
            If filled in, crew will see an amber "Updated Call Sheet" banner at the top of the email and the subject line will read "UPDATED: Call Sheet".
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Resends to all {crewWithEmail.length} {crewWithEmail.length === 1 ? "crew member" : "crew members"}
            {contactCount > 0 && <> and up to {contactCount} agency &amp; client {contactCount === 1 ? "contact" : "contacts"}</>}
            {crewMissingEmail > 0 && <> ({crewMissingEmail} without an email won&rsquo;t receive it)</>}.
          </p>
          <div className="flex justify-end gap-2 mt-3">
            <button
              onClick={() => { setShowUpdatePanel(false); setUpdateNote(""); }}
              disabled={sending}
              className="btn btn-ghost"
            >
              Cancel
            </button>
            <button onClick={() => handleSend()} disabled={sending} className="btn btn-primary">
              {sending ? "Sending…" : "Send update"}
            </button>
          </div>
        </div>
      )}

      {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}
      {sendResult && (
        <div className="card px-5 py-3 flex items-center gap-3" style={{ borderLeft: "3px solid var(--success)" }}>
          <span className="text-base leading-none" style={{ color: "var(--success)" }}>✓</span>
          <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{sendResult}</span>
        </div>
      )}

      {/* Generation progress */}
      {generating && (
        <div className="card px-5 py-6">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{statusMsg}</p>
            <p className="text-xs tabular-nums" style={{ color: "var(--text-muted)" }}>{Math.round(progress)}%</p>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-elevated)" }}>
            <div
              className="h-full rounded-full transition-all duration-400 ease-linear"
              style={{ width: `${progress}%`, background: "var(--accent)" }}
            />
          </div>
        </div>
      )}

      {/* The sheet itself sits directly under the Generate/Send buttons — it is
          what the producer is about to send, so it outranks the checklist and
          the confirmation tracker below. */}
      {!generating && sheet && (
        <div>
          {/* The producer sees what their crew will see on the confirm page.
              It is NOT part of sheet.html_content — that HTML is what goes to
              email and what WeasyPrint prints, and it stays untouched. This is
              a frame around it on screen, which is the whole reason the PDF
              needs no special handling. */}
          {brand.name && (
            <div className="mb-3">
              <TitleCard
                name={brand.name}
                accent={brand.accent}
                image={brand.image}
                nameInImage={brand.nameInImage}
                kind="Call sheet"
                subject={project?.name || undefined}
              />
            </div>
          )}
          <div className="flex justify-end mb-2">
            <button onClick={handleDownloadPDF} disabled={downloading} className="btn btn-ghost btn-sm">
              {downloading ? "Preparing…" : "Download PDF"}
            </button>
          </div>
          <div ref={sheetContainerRef} className="card overflow-hidden">
            <div
              className="p-1"
              style={sheetZoom < 1 ? { zoom: sheetZoom, width: `${100 / sheetZoom}%` } : undefined}
              dangerouslySetInnerHTML={{ __html: cleanSheetHtml(sheet.html_content) }}
            />
          </div>
        </div>
      )}

      {/* Pre-flight — always lists every item so the producer can eyeball the
          full checklist; a green check marks each one that's ready. */}
      {checks.length > 0 && (
        <div className="card divide-y" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center justify-between px-5 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Pre-flight</p>
            {allClear && <span className="badge-confirmed">All clear</span>}
          </div>
          {checks.map((check) => (
            <div key={check.label} className="flex items-center justify-between px-5 py-3">
              <div className="flex items-center gap-3">
                <span className="w-4 flex justify-center shrink-0">
                  {check.ok ? (
                    <span className="text-sm leading-none font-semibold" style={{ color: "var(--success)" }}>✓</span>
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--text-muted)" }} />
                  )}
                </span>
                <span className="text-sm" style={{ color: "var(--text-primary)" }}>{check.label}</span>
                {check.detail && <span className="text-xs" style={{ color: "var(--text-muted)" }}>{check.detail}</span>}
              </div>
              {!check.ok && (
                <Link href={check.fix} className="text-xs" style={{ color: "var(--accent-hover)" }}>
                  {check.fixLabel} →
                </Link>
              )}
            </div>
          ))}
          {/* Deliberately outside `checks` — someone can belong on the sheet
              without being on the shoot, so this is a notice to confirm, not a
              failure that would hold "All clear" hostage forever. */}
          {noCallTimeCount > 0 && (
            <div className="flex items-center justify-between px-5 py-3">
              <div className="flex items-center gap-3">
                <span className="w-4 flex justify-center shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--text-muted)" }} />
                </span>
                <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                  {noCallTimeCount} {noCallTimeCount === 1 ? "crew member has" : "crew have"} no call time
                </span>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>shows as N/A on the sheet</span>
              </div>
              <Link href={`/projects/${id}/crew`} className="text-xs" style={{ color: "var(--accent-hover)" }}>
                Review →
              </Link>
            </div>
          )}
        </div>
      )}

      {/* Confirmation tracker */}
      {hasSent && crew.length > 0 && (
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4">
            <div>
              <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>Confirmations</p>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                {confirmed.length} of {crew.length} received
              </p>
              {/* Say who sends the text, so nobody expects it to go out on its
                  own — the whole point is that it comes from their number. */}
              {confirmed.length < crew.length && Object.keys(nudges).length > 0 && (
                <p className="text-xs mt-1.5" style={{ color: "var(--text-muted)" }}>
                  {onPhone
                    ? "“Text” opens Messages with the note written — you send it."
                    : "“Copy text” copies a ready-to-send note for your phone."}
                </p>
              )}
            </div>
            <button onClick={refreshCrew} disabled={loadingCrew} className="btn btn-ghost btn-sm">
              {loadingCrew ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {/* Progress bar */}
          <div className="h-px mx-5" style={{ background: "var(--border)" }}>
            <div
              className="h-px transition-all duration-500"
              style={{ width: crew.length ? `${(confirmed.length / crew.length) * 100}%` : "0%", background: "var(--accent)" }}
            />
          </div>

          <div className="divide-y" style={{ borderColor: "var(--border)" }}>
            {crew.map((member) => (
              <div key={member.id} className="flex items-center justify-between px-5 py-3">
                <div className="flex items-center gap-3">
                  <div
                    className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0"
                    style={{
                      background: member.confirmed_at ? "var(--accent)" : "var(--bg-elevated)",
                      color: member.confirmed_at ? "#fff" : "var(--text-muted)",
                    }}
                  >
                    {member.confirmed_at ? "✓" : initials(member.name)}
                  </div>
                  <div>
                    <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{member.name}</p>
                    {member.role && <p className="text-xs" style={{ color: "var(--text-muted)" }}>{member.role}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {/* Nudge anyone still pending, by text or by email. Someone
                      with neither number nor address can't be reached from here
                      — say so rather than offering a dead button. */}
                  {!member.confirmed_at && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      {nudges[member.id] && (
                        onPhone ? (
                          <a
                            href={smsHref(nudges[member.id].phone, nudges[member.id].message)}
                            onClick={() => setTextedIds((prev) => new Set(prev).add(member.id))}
                            className="btn btn-ghost btn-sm"
                            title={`Text ${member.name} their confirmation link from your phone`}
                          >
                            {textedIds.has(member.id) ? "Text again" : "Text"}
                          </a>
                        ) : (
                          <button
                            onClick={() => handleCopyText(member, nudges[member.id])}
                            className="btn btn-ghost btn-sm"
                            title={`Copy a ready-to-send text for ${member.name} — you send it from your phone`}
                          >
                            {copiedId === member.id ? "Copied" : textedIds.has(member.id) ? "Copy again" : "Copy text"}
                          </button>
                        )
                      )}
                      {member.email ? (
                        <button
                          onClick={() => handleRemind(member)}
                          disabled={remindingId === member.id}
                          className="btn btn-ghost btn-sm"
                          title={`Re-send the call sheet to ${member.name} as a reminder`}
                        >
                          {remindingId === member.id
                            ? "Sending…"
                            : remindedIds.has(member.id) ? "Remind again" : "Remind"}
                        </button>
                      ) : !nudges[member.id] && (
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>No contact info</span>
                      )}
                    </div>
                  )}
                  <div className="text-right">
                    {member.call_time && (
                      <p className="text-xs font-medium tabular-nums" style={{ color: "var(--text-secondary)" }}>{fmt(member.call_time)}</p>
                    )}
                    {member.confirmed_at ? (
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {new Date(member.confirmed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                      </p>
                    ) : (
                      <span className="badge-pending">Pending</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {confirmed.length === crew.length && crew.length > 0 && (
            <div className="px-5 py-3 text-center" style={{ borderTop: "1px solid var(--border)" }}>
              <p className="text-xs font-medium" style={{ color: "var(--success)" }}>All crew confirmed</p>
            </div>
          )}
        </div>
      )}


      {!generating && !sheet && (
        <div className="card p-12 text-center">
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Fill in the sections, then preview your call sheet.
          </p>
        </div>
      )}
    </div>
  );
}
