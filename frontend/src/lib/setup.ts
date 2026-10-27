// A producer's own copy (docs/own-copy-plan.md): is this one, and has it been
// claimed. Read by the login page before anyone has a session, so it goes
// straight to fetch rather than through api.ts's bearer-token client.

import { API_BASE } from "./apiBase";

export interface SetupStatus {
  single_owner: boolean;
  owner_exists: boolean | null;
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const res = await fetch(`${API_BASE}/api/setup/status`);
  if (!res.ok) throw new Error(`setup status ${res.status}`);
  return res.json();
}

export async function createOwner(body: { name: string; email: string; password: string }): Promise<void> {
  const res = await fetch(`${API_BASE}/api/setup/owner`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "Couldn't create the account. Please try again.";
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch { /* keep the fallback */ }
    throw new Error(detail);
  }
}
