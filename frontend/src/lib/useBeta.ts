"use client";

// Whether this person is on the Jobs beta (docs/job-layer-plan.md §11) — only
// the screens are flagged, so every page that needs to choose between the
// Jobs UI and the current one reads this. `null` means "not known yet",
// distinct from `false`, so a page can hold its default render until the
// account's own answer arrives instead of flashing the wrong UI first.

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface BetaRepairReport {
  repair: { jobs_created: number; hires_created: number; crew_linked: number; crew_ambiguous: { crew_id: string; name: string }[] };
  dates: { hires_converted: number; unparsed: { hire_id: string; name: string; line: string }[] } | null;
}

export function useBeta() {
  const [betaJobs, setBetaJobs] = useState<boolean | null>(null);

  const refresh = useCallback(() => {
    api.get<{ beta_jobs: boolean }>("/api/account/beta")
      .then((r) => setBetaJobs(r.beta_jobs))
      .catch(() => setBetaJobs(false)); // fail closed to the version everyone already knows
  }, []);

  useEffect(refresh, [refresh]);

  const setEnabled = useCallback(async (enabled: boolean) => {
    const r = await api.post<{ beta_jobs: boolean; report: BetaRepairReport | null }>("/api/account/beta", { enabled });
    setBetaJobs(r.beta_jobs);
    return r.report;
  }, []);

  return { betaJobs, refresh, setEnabled };
}
