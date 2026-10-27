"use client";

/* Master Access — the operator's 30,000-foot view of the whole site.
 *
 * Deliberately shows counts and metadata only. No crew names, call times,
 * locations or project names appear here, and the endpoint behind it doesn't
 * read them either — knowing an account is busy is the job; knowing what they
 * are shooting is not.
 *
 * The route isn't linked from anywhere in the app. Access is decided server
 * side by OWNER_USER_IDS, and a non-owner gets a 404 from the API, which this
 * page renders as an ordinary "page not found" rather than "access denied" —
 * no point confirming the route exists to someone probing for it.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { LoadError } from "@/components/LoadError";

interface Account {
  email: string;
  signed_up_at: string | null;
  last_sign_in_at: string | null;
  last_activity: string | null;
  projects: number;
  new_projects: number;
  sheets_stored: number;
  sheets_sent: number;
  recipients: number;
  recipients_window: number;
  confirms: number;
  confirms_window: number;
  generates: number;
  sends: number;
  reminders: number;
  emails: number;
  imports: number;
  import_cost_usd: number;
}

interface Day {
  date: string;
  generates: number;
  sends: number;
  reminders: number;
  emails: number;
  imports: number;
}

interface ImportSource {
  event_type: string;
  label: string;
  count: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

interface ImportPrice {
  model: string;
  input_per_mtok_usd: number;
  output_per_mtok_usd: number;
}

interface Overview {
  generated_at: string;
  window_days: number;
  event_log: { available: boolean; since: string | null; total: number };
  totals: {
    accounts: number;
    active_accounts: number;
    projects: number;
    call_sheets_stored: number;
    generates: number;
    sends: number;
    reminders: number;
    emails: number;
    confirms: number;
    confirms_window: number;
    estimated_cost_usd: number;
    cost_rate_usd: number;
    imports: number;
    import_input_tokens: number;
    import_output_tokens: number;
    import_cost_usd: number;
    import_unpriced: number;
    import_by_source: ImportSource[];
    import_prices: ImportPrice[];
    import_models_unpriced: string[];
  };
  daily: Day[];
  accounts: Account[];
}

const WINDOWS = [7, 30, 90];

function ago(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-4">
      <p className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>{label}</p>
      <p className="text-2xl font-semibold tabular-nums" style={{ color: "var(--text-primary)" }}>{value}</p>
      {sub && <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{sub}</p>}
    </div>
  );
}

/* Daily generates and sends, as two stacked segments per day.
 *
 * Hand-rolled rather than pulling in a chart library: it is a dozen bars with
 * no axes, interaction or scales worth the dependency. Every day in the window
 * gets a column even when it is empty (the API pre-seeds them), so a quiet
 * stretch reads as a gap instead of silently collapsing the timeline. */
function ActivityChart({ daily }: { daily: Day[] }) {
  const max = Math.max(1, ...daily.map((d) => d.generates + d.sends + d.reminders));
  const totalEvents = daily.reduce((n, d) => n + d.generates + d.sends + d.reminders, 0);

  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between mb-3">
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>Activity per day</p>
        <div className="flex items-center gap-3 text-xs" style={{ color: "var(--text-secondary)" }}>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-sm" style={{ background: "var(--accent)" }} />
            generates
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-sm" style={{ background: "var(--success)" }} />
            sends &amp; reminders
          </span>
        </div>
      </div>

      {totalEvents === 0 ? (
        <p className="text-xs py-8 text-center" style={{ color: "var(--text-muted)" }}>
          No generates or sends recorded in this window.
        </p>
      ) : (
        <div
          className="flex items-end gap-px h-32"
          role="img"
          aria-label={`Daily activity over ${daily.length} days: ${totalEvents} events in total, busiest day ${max}.`}
        >
          {daily.map((d) => {
            const stack = d.generates + d.sends + d.reminders;
            return (
              <div
                key={d.date}
                className="flex-1 flex flex-col justify-end h-full rounded-sm"
                style={{ background: "var(--bg-inset)", minWidth: "2px" }}
                title={`${d.date} — ${d.generates} generated, ${d.sends} sent, ${d.reminders} reminded, ${d.emails} emails, ${d.imports ?? 0} AI imports`}
              >
                {d.sends + d.reminders > 0 && (
                  <div style={{ height: `${((d.sends + d.reminders) / max) * 100}%`, background: "var(--success)" }} />
                )}
                {d.generates > 0 && (
                  <div style={{ height: `${(d.generates / max) * 100}%`, background: "var(--accent)" }} />
                )}
                {stack === 0 && <div style={{ height: "2px", background: "var(--border)" }} />}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex justify-between mt-2 text-xs" style={{ color: "var(--text-muted)" }}>
        <span>{daily[0]?.date}</span>
        <span>{daily[daily.length - 1]?.date}</span>
      </div>
    </div>
  );
}

/* Claude spend — two figures that are NOT the same kind of number, so each is
 * labelled with how it was arrived at and shown with the rate behind it.
 *
 *   Measured  AI imports (paste-a-list, call sheet PDF). Each records the token
 *             counts the model reported; spend is those tokens at the listed
 *             published price. Zero until supabase/usage_import_events.sql runs.
 *   Assumed   call sheet generations: a flat rate times a count, unchanged. */
function SpendCard({ t, windowDays }: { t: Overview["totals"]; windowDays: number }) {
  const rates = t.import_prices
    .map((p) => `${p.model} at $${p.input_per_mtok_usd.toFixed(2)} in / $${p.output_per_mtok_usd.toFixed(2)} out per 1M tokens`)
    .join("; ");
  const sources = t.import_by_source.filter((s) => s.count > 0);
  return (
    <div className="card p-4 space-y-4 text-xs" style={{ color: "var(--text-muted)" }}>
      <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>Claude spend, {windowDays}d</p>

      <div className="space-y-1">
        <p>
          <span style={{ color: "var(--text-secondary)" }}>AI imports — measured: </span>
          <span className="tabular-nums" style={{ color: "var(--text-primary)" }}>${t.import_cost_usd.toFixed(2)}</span>
          {/* Template literals throughout: JSX drops the space between an
              expression and the text after it (it once rendered "$0.05each"). */}
          {` — ${t.imports} ${t.imports === 1 ? "import" : "imports"}, ${t.import_input_tokens.toLocaleString()} input / ${t.import_output_tokens.toLocaleString()} output tokens, priced at ${rates}.`}
        </p>
        {sources.length > 0 && (
          <ul className="pl-3 space-y-0.5">
            {sources.map((s) => (
              <li key={s.event_type} className="tabular-nums">
                {`${s.label}: ${s.count} · $${s.cost_usd.toFixed(2)}`}
              </li>
            ))}
          </ul>
        )}
        {t.import_unpriced > 0 && (
          <p>
            {`${t.import_unpriced} ${t.import_unpriced === 1 ? "import" : "imports"} used a model with no listed price (${t.import_models_unpriced.join(", ") || "model not recorded"}) and ${t.import_unpriced === 1 ? "is" : "are"} left out of the total rather than guessed.`}
          </p>
        )}
        {t.imports === 0 && (
          <p>No imports recorded in this window. Recording starts once supabase/usage_import_events.sql has been run on this database.</p>
        )}
      </div>

      <div>
        <p>
          <span style={{ color: "var(--text-secondary)" }}>Call sheet generations — assumed: </span>
          <span className="tabular-nums" style={{ color: "var(--text-primary)" }}>${t.estimated_cost_usd.toFixed(2)}</span>
          {` — ${t.generates} generations at an assumed $${t.cost_rate_usd.toFixed(2)} each.`}
          {" Per-generation token counts aren't recorded, so this is a rate applied to a count, not a bill."}
        </p>
      </div>
    </div>
  );
}

export default function MasterAccessPage() {
  const router = useRouter();
  const [data, setData] = useState<Overview | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [dark, setDark] = useState(true);

  useEffect(() => {
    setDark(document.documentElement.getAttribute("data-theme") !== "light");
  }, []);

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  const load = useCallback((window: number) => {
    setLoading(true);
    setLoadError(false);
    api.get<Overview>(`/api/admin/overview?days=${window}`)
      .then(setData)
      .catch((err: unknown) => {
        // 404 is what a non-owner gets. Anything else is a real failure.
        if ((err as { status?: number })?.status === 404) setDenied(true);
        else setLoadError(true);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) { router.replace("/auth/login"); return; }
      load(days);
    });
  }, [router, load, days]);

  if (denied) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3" style={{ background: "var(--bg-base)" }}>
        <p className="text-sm" style={{ color: "var(--text-primary)" }}>This page could not be found.</p>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">Back to dashboard</Link>
      </div>
    );
  }

  const t = data?.totals;

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }}>
      <header
        className="sticky top-0 z-10 px-6 py-3 flex items-center justify-between"
        style={{ background: "var(--bg-sidebar)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-baseline gap-3">
          <span className="text-sm font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>SET&gt;READY</span>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>Master Access</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="text-xs" style={{ color: "var(--text-secondary)" }}>Dashboard</Link>
          <button onClick={toggleTheme} className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {dark ? "Light mode" : "Dark mode"}
          </button>
        </div>
      </header>

      <main className="flex-1 w-full max-w-5xl mx-auto px-6 py-8 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Site overview</h1>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              {data ? `As of ${new Date(data.generated_at).toLocaleString()}` : "Counts and metadata only — no shoot content."}
            </p>
          </div>
          <div className="flex items-center gap-1" role="group" aria-label="Time window">
            {WINDOWS.map((w) => (
              <button
                key={w}
                onClick={() => setDays(w)}
                aria-pressed={days === w}
                className="btn btn-sm"
                style={
                  days === w
                    ? { background: "var(--accent)", color: "#fff" }
                    : { background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border)" }
                }
              >
                {w}d
              </button>
            ))}
          </div>
        </div>

        {loadError && <LoadError message="Couldn't load the site overview." onRetry={() => load(days)} />}

        {loading && !data && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} height="5.5rem" />)}
            </div>
            <Skeleton height="11rem" />
            <Skeleton height="16rem" />
          </div>
        )}

        {data && t && (
          <div className={loading ? "space-y-6 opacity-60 transition-opacity" : "space-y-6 transition-opacity"}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat
                label="Accounts"
                value={String(t.accounts)}
                sub={`${t.active_accounts} active in ${data.window_days}d`}
              />
              <Stat
                label="Projects"
                value={String(t.projects)}
                sub={`${t.call_sheets_stored} call sheets stored`}
              />
              <Stat
                label={`Generated (${data.window_days}d)`}
                value={String(t.generates)}
                sub={`${t.sends} sent${t.reminders ? ` · ${t.reminders} reminded` : ""} · ${t.emails} emails`}
              />
              <Stat
                label="Confirmations"
                value={String(t.confirms)}
                sub={`${t.confirms_window} in ${data.window_days}d`}
              />
            </div>

            <ActivityChart daily={data.daily} />

            <div className="card overflow-hidden">
              <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
                <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>Accounts</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                  Most recently active first. Recipients and confirmations are totals to date; the
                  bracketed figure is the last {data.window_days} days.
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs" style={{ color: "var(--text-secondary)" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      <th className="text-left font-medium px-4 py-2">Account</th>
                      <th className="text-right font-medium px-2 py-2">Proj</th>
                      <th className="text-right font-medium px-2 py-2">Sheets</th>
                      <th className="text-right font-medium px-2 py-2">Sent</th>
                      <th className="text-right font-medium px-2 py-2">Recipients</th>
                      <th className="text-right font-medium px-2 py-2">Confirms</th>
                      <th className="text-right font-medium px-2 py-2">Gen</th>
                      <th className="text-right font-medium px-2 py-2">Imports</th>
                      <th className="text-right font-medium px-4 py-2">Last active</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.accounts.map((a) => {
                      const dormant = !a.last_activity;
                      return (
                        <tr key={a.email} style={{ borderBottom: "1px solid var(--border)", opacity: dormant ? 0.55 : 1 }}>
                          <td className="px-4 py-2" style={{ color: "var(--text-primary)" }}>
                            {a.email}
                            {a.signed_up_at && (
                              <span className="block" style={{ color: "var(--text-muted)" }}>
                                joined {ago(a.signed_up_at)}
                              </span>
                            )}
                          </td>
                          <td className="text-right px-2 py-2 tabular-nums">{a.projects}</td>
                          <td className="text-right px-2 py-2 tabular-nums">{a.sheets_stored}</td>
                          <td className="text-right px-2 py-2 tabular-nums">{a.sheets_sent}</td>
                          <td className="text-right px-2 py-2 tabular-nums">
                            {a.recipients}
                            <span style={{ color: "var(--text-muted)" }}> ({a.recipients_window})</span>
                          </td>
                          <td className="text-right px-2 py-2 tabular-nums">
                            {a.confirms}
                            <span style={{ color: "var(--text-muted)" }}> ({a.confirms_window})</span>
                          </td>
                          <td className="text-right px-2 py-2 tabular-nums">{a.generates}</td>
                          <td
                            className="text-right px-2 py-2 tabular-nums"
                            title={a.imports ? `$${a.import_cost_usd.toFixed(2)} measured` : undefined}
                          >
                            {a.imports}
                          </td>
                          <td className="text-right px-4 py-2 whitespace-nowrap">{ago(a.last_activity)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <SpendCard t={t} windowDays={data.window_days} />

            <div className="card p-4 space-y-2 text-xs" style={{ color: "var(--text-muted)" }}>
              <p>
                {data.event_log.available
                  ? data.event_log.total > 0
                    ? `Event log covers ${ago(data.event_log.since)} onward (${data.event_log.total} events). Generate, send and remind counts only exist from then on.`
                    : "Event log is live but empty — nothing has been generated or sent since it went up."
                  : "Event log table is missing, so generate/send counts are unavailable."}
              </p>
              <p>
                Projects, sheets, recipients and confirmations are read from current state, so they are a
                floor rather than an exact count: generating a call sheet deletes the project&apos;s previous
                one, and a re-send overwrites the last-sent timestamp.
              </p>
              <p>
                No crew names, phone numbers, project names or locations are read to build this page.
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
