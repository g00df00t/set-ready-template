"use client";

/* Back and forward links at the foot of every setup page.
 *
 * On the Crew page there was nothing telling a producer what to do once the list
 * was built — the only way onward was to guess at the sidebar. The sidebar can
 * do both jobs, but it asks you to remember where you were in a sequence you
 * shouldn't have to hold in your head.
 *
 * Back is quieter than Next on purpose: forward is the task, back is the
 * occasional "I forgot to add someone". Both name their destination rather than
 * saying Back/Next alone, so you know where you'll land without counting.
 *
 * Rendered from the project layout so there is one placement rather than ten,
 * and returns null on pages outside the setup sequence (the overview, Notes).
 */

import Link from "next/link";
import { nextStepAfter, prevStepBefore } from "@/lib/setupSteps";

export function StepNav({ projectId, path }: { projectId: string; path: string }) {
  const prev = prevStepBefore(path);
  const next = nextStepAfter(path);
  if (!prev && !next) return null;

  return (
    <div className="max-w-5xl mx-auto w-full px-4 md:px-8 pt-5 pb-10 flex items-center justify-between gap-3">
      {/* Placeholders keep Next hard right on the first and last steps, where
          only one of the two links exists. */}
      {prev ? (
        <Link href={`/projects/${projectId}${prev.path}`} className="btn btn-ghost btn-sm">
          <span aria-hidden="true" className="mr-1.5">&larr;</span>
          {prev.name}
        </Link>
      ) : (
        <span />
      )}
      {next ? (
        <Link href={`/projects/${projectId}${next.path}`} className="btn btn-secondary btn-sm">
          Next: {next.name}
          {next.optional && (
            <span className="ml-1.5" style={{ color: "var(--text-muted)" }}>optional</span>
          )}
          <span aria-hidden="true" className="ml-1.5">&rarr;</span>
        </Link>
      ) : (
        <span />
      )}
    </div>
  );
}
