"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { TimeInput } from "@/components/TimeInput";
import { useToast } from "@/components/Toast";
import { FormCardSkeleton } from "@/components/Skeleton";

interface MealPlan {
  breakfast_start: string;
  breakfast_end: string;
  breakfast_notes: string;
  lunch_start: string;
  lunch_end: string;
  lunch_notes: string;
}

const EMPTY: MealPlan = {
  breakfast_start: "", breakfast_end: "", breakfast_notes: "",
  lunch_start: "", lunch_end: "", lunch_notes: "",
};

// Stored times come back as 06:00:00; the field wants 6:00 AM.
function display(t: string | null | undefined): string {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  if (Number.isNaN(h)) return t;
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

const MEALS = [
  {
    key: "breakfast",
    label: "Breakfast",
    startPlaceholder: "7:00 AM",
    endPlaceholder: "8:00 AM",
    notesPlaceholder: "Served in the merch room on the 5th floor.",
  },
  {
    key: "lunch",
    label: "Lunch",
    startPlaceholder: "12:30 PM",
    endPlaceholder: "1:15 PM",
    notesPlaceholder: "Walk-away lunch. Cookshop, 156 10th Ave — production will shuttle.",
  },
] as const;

export default function MealsPage() {
  const { id } = useParams<{ id: string }>();
  // Cached by URL — a revisit within the session shows the last saved values
  // instantly instead of a blank form under the skeleton. The response is the
  // server's raw shape (HH:MM:SS); `form` is the locally-typed, always-AM/PM
  // shape the inputs actually use, so it's hydrated from the cache once below
  // rather than read from it directly. A 404 just means no meal plan yet — the
  // normal starting state — so SWR's `error` is never surfaced; `saved` stays
  // undefined and the form stays at its EMPTY default.
  const { data: saved, isLoading: loading, mutate: mutateMeals } =
    useSWR<Partial<Record<keyof MealPlan, string | null>>>(`/api/projects/${id}/meals`, api.get);
  const [form, setForm] = useState<MealPlan>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { show: showToast, node: toastNode } = useToast();

  const hydrated = useRef(false);
  useEffect(() => {
    if (!loading && !hydrated.current) {
      hydrated.current = true;
      // Named fields only — the response also carries id and project_id, and
      // spreading the whole object would send them straight back on save.
      if (saved) setForm({
        breakfast_start: display(saved.breakfast_start),
        breakfast_end: display(saved.breakfast_end),
        breakfast_notes: saved.breakfast_notes ?? "",
        lunch_start: display(saved.lunch_start),
        lunch_end: display(saved.lunch_end),
        lunch_notes: saved.lunch_notes ?? "",
      });
    }
  }, [loading, saved]);

  function set(key: keyof MealPlan, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError("");
    try {
      const saved = await api.put<Partial<Record<keyof MealPlan, string | null>>>(
        `/api/projects/${id}/meals`, form,
      );
      mutateMeals(saved, false);
      // Reflect what was actually stored, so "7am" comes back as 7:00 AM and
      // the producer can see the sheet will read the way they expect.
      setForm({
        breakfast_start: display(saved.breakfast_start),
        breakfast_end: display(saved.breakfast_end),
        breakfast_notes: saved.breakfast_notes ?? "",
        lunch_start: display(saved.lunch_start),
        lunch_end: display(saved.lunch_end),
        lunch_notes: saved.lunch_notes ?? "",
      });
      showToast("Meal plan saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the meal plan");
    } finally { setSaving(false); }
  }

  return (
    <div className="px-6 py-8 max-w-5xl mx-auto space-y-6">
      {toastNode}

      <div>
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Meal Plan</h2>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          When and where crew eat. Optional — leave a meal blank and it won&rsquo;t appear
          on the call sheet. Fill in nothing and the whole section stays off.
        </p>
      </div>

      {loading ? (
        <FormCardSkeleton blocks={2} />
      ) : (
        <form onSubmit={handleSave} className="space-y-4">
          {MEALS.map((meal) => (
            <div key={meal.key} className="card p-5 space-y-4">
              <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                {meal.label}
              </p>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="field-label">Start</label>
                  <TimeInput
                    ariaLabel={`${meal.label} start time`}
                    value={form[`${meal.key}_start`]}
                    onChange={(v) => set(`${meal.key}_start`, v)}
                    placeholder={meal.startPlaceholder}
                  />
                </div>
                <div>
                  <label className="field-label">Finish</label>
                  <TimeInput
                    ariaLabel={`${meal.label} finish time`}
                    value={form[`${meal.key}_end`]}
                    onChange={(v) => set(`${meal.key}_end`, v)}
                    placeholder={meal.endPlaceholder}
                  />
                </div>
              </div>

              <div>
                <label className="field-label">Notes</label>
                <textarea
                  aria-label={`${meal.label} notes`}
                  rows={2}
                  value={form[`${meal.key}_notes`]}
                  onChange={(e) => set(`${meal.key}_notes`, e.target.value)}
                  placeholder={meal.notesPlaceholder}
                  className="field-input resize-none"
                />
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  Printed on the call sheet exactly as you write it.
                </p>
              </div>
            </div>
          ))}

          {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

          <div className="flex justify-end">
            <button type="submit" disabled={saving} className="btn btn-primary">
              {saving ? "Saving…" : "Save meal plan"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
