"use client";

import { useEffect, useState } from "react";
import { TimeInput } from "@/components/TimeInput";
import { CALL_TIME_LABELS } from "@/lib/time";

/**
 * Always-editable call-time field for a list row. Commits on blur only when the
 * value actually changed, so there's no Edit → type → Save round-trip. Shared by
 * the Crew, Talent, and Agency & Client tabs so call-time editing is consistent.
 *
 * `onSave` is expected to reject when the API refuses the value. A typo'd time
 * ("2AA") comes back from the backend as a 422 naming the offending text and the
 * formats that would work, and that sentence belongs on the field that produced
 * it — not in a toast that leaves before the producer has looked up.
 */
export function InlineCallTime({ initial, onSave, saving, floatAlign = "left" }: { initial: string; onSave: (v: string) => void | Promise<void>; saving: boolean; floatAlign?: "left" | "right" }) {
  const [val, setVal] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  // The exact text the server already refused. Blur fires again every time the
  // producer clicks back into the cell and out of it, and without this each of
  // those re-sends a value we know is bad.
  const [rejected, setRejected] = useState<string | null>(null);

  useEffect(() => { setVal(initial); setError(null); setRejected(null); }, [initial]);

  async function commit() {
    if (val === initial || val === rejected) return;
    setError(null);
    try {
      await onSave(val);
      setRejected(null);
    } catch (err) {
      // Deliberately keep what they typed. Reverting to the old value would
      // erase the evidence of the mistake and leave a stale time on the sheet
      // looking deliberate. Focus is deliberately NOT taken back either — the
      // producer is already tabbing down a column, and a field that grabs focus
      // on every blur is a trap they can't leave.
      setError(err instanceof Error ? err.message : "That call time couldn't be saved.");
      setRejected(val);
    }
  }

  return (
    // Positioned so the floated message anchors to this cell. inline-block, not
    // block: the fixed width below is what gives the table column something to
    // measure, and a full-width block would give that back.
    <span style={{ position: "relative", display: "inline-block" }}>
      <TimeInput
        ariaLabel="Call time"
        // Empty means no call time, which is a valid choice — so say "N/A" rather
        // than ghosting "8:00 AM", which scans as a real time in a dense table.
        placeholder="N/A"
        suggestions={CALL_TIME_LABELS}
        value={val}
        onChange={(v) => { setVal(v); if (error) { setError(null); setRejected(null); } }}
        onBlur={commit}
        className="py-1"
        error={error}
        floatError={floatAlign}
        // A fixed width, not maxWidth. .field-input is width:100%, which contributes
        // no intrinsic width to an auto-layout table — the column collapsed to the
        // header's minimum and clipped the time to "9:(", and widening the window
        // didn't help because the extra space went to the text columns instead.
        style={{ width: "7.5rem", opacity: saving ? 0.6 : 1 }}
      />
    </span>
  );
}
