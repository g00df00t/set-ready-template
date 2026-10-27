"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { TimeInput } from "@/components/TimeInput";
import { useToast } from "@/components/Toast";
import { FormCardSkeleton } from "@/components/Skeleton";

interface Accommodation {
  hotel_name: string;
  address: string;
  phone: string;
  website_url: string;
  room_block: string;
  check_in_time: string;
  check_out_time: string;
  amenities: string;
  notes: string;
}

const EMPTY: Accommodation = {
  hotel_name: "", address: "", phone: "", website_url: "",
  room_block: "", check_in_time: "", check_out_time: "", amenities: "", notes: "",
};

export default function AccommodationsPage() {
  const { id } = useParams<{ id: string }>();
  // Cached by URL — a revisit within the session shows the last saved values
  // instantly instead of a blank form under the skeleton. `form` is hydrated
  // from the cache once below rather than read from it directly, the same
  // pattern as Meals. A 404 just means this job has no hotel — the common
  // case on a local shoot — so SWR's `error` is never surfaced; `saved` stays
  // undefined and the form stays at its EMPTY default.
  const { data: saved, isLoading: loading, mutate: mutateAccommodation } =
    useSWR<Partial<Record<keyof Accommodation, string | null>>>(`/api/projects/${id}/accommodation`, api.get);
  const [form, setForm] = useState<Accommodation>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { show: showToast, node: toastNode } = useToast();

  const hydrated = useRef(false);
  useEffect(() => {
    if (!loading && !hydrated.current) {
      hydrated.current = true;
      // Pick the known fields by name. The response also carries id and
      // project_id, which are strings too — spreading the whole object would
      // put them in the form and send them straight back.
      if (saved) setForm({
        hotel_name: saved.hotel_name ?? "",
        address: saved.address ?? "",
        phone: saved.phone ?? "",
        website_url: saved.website_url ?? "",
        room_block: saved.room_block ?? "",
        check_in_time: saved.check_in_time ?? "",
        check_out_time: saved.check_out_time ?? "",
        amenities: saved.amenities ?? "",
        notes: saved.notes ?? "",
      });
    }
  }, [loading, saved]);

  function set(key: keyof Accommodation, val: string) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setError("");
    try {
      await api.put(`/api/projects/${id}/accommodation`, form);
      mutateAccommodation(form, false);
      showToast("Accommodations saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save accommodations");
    } finally { setSaving(false); }
  }

  const hasAny = Object.values(form).some((v) => v.trim() !== "");

  return (
    <div className="px-6 py-8 max-w-5xl mx-auto space-y-6">
      {toastNode}

      <div>
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>Accommodations</h2>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          Where the crew are staying. Optional — leave it blank on a local shoot and
          the call sheet won&rsquo;t show this section at all.
        </p>
      </div>

      {loading ? (
        <FormCardSkeleton fields={4} />
      ) : (
        <form onSubmit={handleSave} className="card p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="field-label">Hotel name</label>
              <input aria-label="Hotel name" value={form.hotel_name} onChange={(e) => set("hotel_name", e.target.value)} placeholder="The Ace Hotel" className="field-input" />
            </div>
            <div>
              <label className="field-label">Front desk phone</label>
              <input aria-label="Front desk phone" value={form.phone} onChange={(e) => set("phone", e.target.value)} placeholder="(503) 555-0142" className="field-input" />
            </div>
          </div>

          <div>
            <label className="field-label">Address</label>
            <input aria-label="Address" value={form.address} onChange={(e) => set("address", e.target.value)} placeholder="929 SW Harvey Milk St, Portland, OR" className="field-input" />
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Adds map links and the distance from set to the call sheet.
            </p>
          </div>

          <div>
            <label className="field-label">Hotel website</label>
            <input aria-label="Hotel website" type="url" value={form.website_url} onChange={(e) => set("website_url", e.target.value)} placeholder="https://www.acehotel.com/portland" className="field-input" />
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Crew can open this to look around for themselves.
            </p>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="field-label">Room block</label>
              <input aria-label="Room block" value={form.room_block} onChange={(e) => set("room_block", e.target.value)} placeholder="Northwind Production" className="field-input" />
            </div>
            <div><label className="field-label">Check-in</label><TimeInput value={form.check_in_time} onChange={(v) => set("check_in_time", v)} placeholder="3:00 PM" /></div>
            <div><label className="field-label">Check-out</label><TimeInput value={form.check_out_time} onChange={(v) => set("check_out_time", v)} placeholder="11:00 AM" /></div>
          </div>

          <div>
            <label className="field-label">Amenities</label>
            <textarea
              aria-label="Amenities"
              rows={3}
              value={form.amenities}
              onChange={(e) => set("amenities", e.target.value)}
              placeholder="Gym on 2, open 24h · Rooftop bar until 11 · No pool · Free breakfast 6–10am"
              className="field-input resize-none"
            />
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Printed on the call sheet exactly as you write it.
            </p>
          </div>

          <div>
            <label className="field-label">Notes</label>
            <textarea aria-label="Notes" rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Valet only, $45/night. Ask for the production rate." className="field-input resize-none" />
          </div>

          {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

          <div className="flex justify-end">
            <button type="submit" disabled={saving || !hasAny} className="btn btn-primary">
              {saving ? "Saving…" : "Save accommodations"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
