"""Putting existing data into the job shape (docs/job-layer-plan.md §8 steps
2–3), and the one-time conversion when an account opts in to Jobs (§11).

Used three ways, so it lives here rather than in a script:

  - scripts/backfill_jobs.py        the migration's backfill, every account
  - POST /account/beta              the repair run before an account switches
  - tests/test_job_migration.py     without a database

Idempotent throughout. A project that already has a job is left alone; a crew
row that already has a hire is left alone. Re-running after a partial failure
picks up exactly what's missing, which is what makes it safe to use as the
repair for anything the best-effort bookkeeping (services/job_hires.py) missed.

`apply=False` reads everything and writes nothing, and reports what it would
have done — same contract as backfill_roster_links.py.
"""

from collections import defaultdict
from datetime import date

from services import job_dates
from services.job_hires import HIRE_FIELDS, job_from_project, _match_hire
from services.person_match import Verdict


def backfill(client, owner_ids: list[str] | None = None, apply: bool = False) -> dict:
    """One job per job-less project, one hire per unlinked crew row.

    Scoped to `owner_ids` when given (the per-account repair), everything
    otherwise (the migration). Returns counts plus anything a human should
    look at.
    """
    report = {"jobs_created": 0, "projects_linked": 0, "hires_created": 0,
              "crew_linked": 0, "crew_already_linked": 0, "crew_ambiguous": [],
              "legacy_dates_rows": 0}

    q = client.table("projects").select("*")
    if owner_ids is not None:
        q = q.in_("owner_id", list(owner_ids))
    projects = q.execute().data

    # ── Step 2a: a job for every project without one ─────────────────────────
    for p in projects:
        if p.get("job_id"):
            continue
        report["jobs_created"] += 1
        report["projects_linked"] += 1
        if apply:
            job = client.table("jobs").insert(job_from_project(p)).execute().data[0]
            client.table("projects").update({"job_id": job["id"]}).eq("id", p["id"]).execute()
            p["job_id"] = job["id"]
        else:
            p["job_id"] = f"(new job for {p['id']})"

    if not projects:
        return report
    job_of = {p["id"]: p["job_id"] for p in projects}

    # ── Step 2b: a hire for every crew row without one ───────────────────────
    crew = client.table("crew_members").select("*").in_("project_id", list(job_of)).order(
        "sort_order").execute().data
    real_job_ids = [j for j in set(job_of.values()) if not str(j).startswith("(")]
    hires_by_job: dict[str, list] = defaultdict(list)
    if real_job_ids:
        for h in client.table("job_hires").select("*").in_("job_id", real_job_ids).execute().data:
            if h.get("kind") != "talent":       # crew rows only ever match crew hires
                hires_by_job[h["job_id"]].append(h)

    for row in crew:
        if (row.get("deal_memo_dates") or "").strip():
            report["legacy_dates_rows"] += 1
        if row.get("hire_id"):
            report["crew_already_linked"] += 1
            continue
        job_id = job_of[row["project_id"]]
        hires = hires_by_job[job_id]
        verdict, entry = _match_hire(row, hires)
        if verdict is Verdict.AMBIGUOUS:
            # Two hires on this job already fit. Choosing would merge two
            # humans; leave the row unlinked and say so.
            report["crew_ambiguous"].append({"crew_id": row["id"], "name": row.get("name")})
            continue
        if verdict is Verdict.MATCH:
            hire = entry
        else:
            hire = {"job_id": job_id, "roster_id": row.get("roster_id"),
                    "sort_order": len(hires),
                    **{k: (row.get(k) or None) for k in HIRE_FIELDS}}
            report["hires_created"] += 1
            if apply:
                hire = client.table("job_hires").insert(hire).execute().data[0]
            else:
                hire["id"] = f"(new hire {len(hires)})"
            hires.append(hire)
        report["crew_linked"] += 1
        if apply:
            client.table("crew_members").update({"hire_id": hire["id"]}).eq("id", row["id"]).execute()

    return report


def convert_legacy_dates(client, owner_ids: list[str], apply: bool = False) -> dict:
    """Old free-text deal memo dates → structured dates on each hire.

    Run once, when an account opts in (plan §11). The two versions don't keep
    these in sync — free text into structured dates is too fragile to do on
    every keystroke, and nobody works in both versions at once.

    A hire that already has custom dates is left alone: it has been edited in
    the Jobs version, and that is the newer truth. Every line that can't be read
    is reported with the person's name, never silently dropped.
    """
    report = {"hires_converted": 0, "hires_skipped_already_custom": 0, "unparsed": []}
    jobs = client.table("jobs").select("id").in_("owner_id", list(owner_ids)).execute().data
    if not jobs:
        return report
    job_ids = [j["id"] for j in jobs]
    hires = client.table("job_hires").select("*").in_("job_id", job_ids).execute().data
    if not hires:
        return report
    days = client.table("projects").select("id,job_id,shoot_date,created_at").in_(
        "job_id", job_ids).execute().data
    rows = client.table("crew_members").select("hire_id,project_id,deal_memo_dates").in_(
        "hire_id", [h["id"] for h in hires]).execute().data

    texts: dict[str, list[str]] = defaultdict(list)
    ref_of: dict[str, date] = {}
    day_by_id = {d["id"]: d for d in days}
    for r in rows:
        text = (r.get("deal_memo_dates") or "").strip()
        if not text:
            continue
        texts[r["hire_id"]].append(text)
        # The lines carry no year. Read them relative to the day they were
        # written on: its shoot date, else when it was created.
        d = day_by_id.get(r["project_id"]) or {}
        ref = d.get("shoot_date") or (d.get("created_at") or "")[:10]
        if ref and r["hire_id"] not in ref_of:
            ref_of[r["hire_id"]] = date.fromisoformat(ref)

    for h in hires:
        if h["id"] not in texts:
            continue
        if job_dates.is_custom(h.get("dates_override")):
            report["hires_skipped_already_custom"] += 1
            continue
        override, unparsed = job_dates.parse_legacy_text(
            texts[h["id"]], ref_of.get(h["id"], date.today()))
        for line in unparsed:
            report["unparsed"].append({"hire_id": h["id"], "name": h.get("name"), "line": line})
        if not override:
            continue
        report["hires_converted"] += 1
        if apply:
            client.table("job_hires").update({"dates_override": override}).eq("id", h["id"]).execute()
    return report
