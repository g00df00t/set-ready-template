import logging
from fastapi import APIRouter, Depends, HTTPException
from database import get_client
from services.receipt_store import delete_job_receipts
from auth import get_current_user, get_write_owner_id
from config import settings
from models.job import BetaToggle, JobDefaults
from services.job_backfill import backfill, convert_legacy_dates
from services.job_rates import clean_defaults

logger = logging.getLogger(__name__)
router = APIRouter(tags=["account"])


@router.delete("/account")
def delete_account(user_id: str = Depends(get_current_user)):
    """Permanently delete the user's account and all of their data.

    Explicitly clear all owned rows before removing the auth user: usage events,
    then projects (which cascades to crew/talent/contacts/schedule/locations/
    call sheets/company moves), then roster and location_roster. Jobs go
    before projects — they cascade to their days and hires — and projects are
    still deleted by owner afterwards for any day that never got a job. Usage events go
    first because their project_id is ON DELETE SET NULL — deleting projects
    would orphan them rather than remove them. The auth user is deleted
    last because projects/roster reference auth.users. This works whether or not
    the DB-level ON DELETE CASCADE constraints are in place (see the cascade
    migration in supabase/schema.sql — it additionally enables dashboard-side
    user deletion).
    """
    client = get_client()
    try:
        client.table("usage_events").delete().eq("user_id", user_id).execute()
        _delete_jobs(client, user_id)
        client.table("projects").delete().eq("owner_id", user_id).execute()
        client.table("roster").delete().eq("owner_id", user_id).execute()
        client.table("location_roster").delete().eq("owner_id", user_id).execute()
        client.auth.admin.delete_user(user_id)
    except Exception as e:
        logger.warning("Account deletion failed for %s: %s", user_id, e)
        raise HTTPException(
            status_code=500,
            detail="Could not delete your account. Please try again or contact support.",
        )
    return {"ok": True}


def _delete_jobs(client, user_id: str) -> None:
    """The user's own jobs — scoped by their owner_id only, never the team's
    accessible set, same rule as every other delete here.

    Not allowed to fail the deletion: jobs.owner_id cascades from auth.users,
    so deleting the auth user at the end removes anything left here anyway,
    and a database without the jobs table yet has nothing to delete.
    """
    try:
        # Their kept receipts first: storage doesn't cascade with the rows. Its
        # own try, so a database without jobs still reaches the delete below.
        for j in client.table("jobs").select("id").eq("owner_id", user_id).execute().data:
            delete_job_receipts(client, j["id"])
    except Exception as e:
        logger.warning("Listing jobs for receipt cleanup failed for %s: %s", user_id, type(e).__name__)
    try:
        client.table("jobs").delete().eq("owner_id", user_id).execute()
    except Exception as e:
        logger.warning("Deleting jobs failed for %s (auth user cascade covers it): %s", user_id, e)


# ── The Jobs beta (docs/job-layer-plan.md §11) ───────────────────────────────
#
# `beta_jobs` in the user's Supabase user_metadata, where Terms acceptance
# lives. Per person, not per account: a team member can be on either version,
# and both read the same data. Only the screens read it. The backend keeps
# everyone's data in the job shape regardless, so the flag is a UI switch —
# user_metadata is user-writable, and that's fine for a UI switch. The one
# exception is the call sheet's "Day 2 of 4" (routers/call_sheet.py), which
# crew see: everyone's Duplicate joins the source's job, so without the flag a
# shoot reused as a template would tell its crew "Day 2 of 2".


def _metadata(client, user_id: str) -> dict:
    return dict(client.auth.admin.get_user_by_id(user_id).user.user_metadata or {})


def on_jobs_beta(client, user_id: str) -> bool:
    """Whether this person has switched to Jobs. Unreadable counts as off —
    the version everyone else sees. A producer's own copy is simply on Jobs:
    there's no "everyone else" there to keep the old version for."""
    if settings.single_owner:
        return True
    try:
        return bool(_metadata(client, user_id).get("beta_jobs"))
    except Exception as e:
        logger.error("Reading the Jobs flag for %s failed: %s", user_id, e, exc_info=True)
        return False


@router.get("/account/beta")
def get_beta(user_id: str = Depends(get_current_user)):
    client = get_client()
    return {"beta_jobs": on_jobs_beta(client, user_id)}


@router.post("/account/beta")
def set_beta(
    data: BetaToggle,
    user_id: str = Depends(get_current_user),
    write_owner_id: str = Depends(get_write_owner_id),
):
    """Switch this person to Jobs, or back.

    Switching ON first repairs the account's data — re-runs the migration's
    backfill for it, so anything the best-effort bookkeeping missed is in place
    — then converts its old free-text deal memo dates onto the hires, once.
    The account is the shared one (write_owner_id): a team member switching
    over sees the owner's jobs, so those are the ones that must be whole.

    Lines that can't be read are returned, with whose they were, so the
    screen can show them rather than lose them.

    Switching OFF changes nothing but the flag. Nothing is converted back —
    the old version still has its own copy of everything it wrote.
    """
    client = get_client()
    meta = _metadata(client, user_id)
    report = None
    if data.enabled:
        try:
            report = {"repair": backfill(client, [write_owner_id], apply=True), "dates": None}
            # Once per person, not on every switch back on: someone who reset a
            # hire to the crew dates in Jobs, switched back, then returned must
            # not get their old lines re-imposed.
            if not meta.get("beta_jobs_dates_converted"):
                report["dates"] = convert_legacy_dates(client, [write_owner_id], apply=True)
                meta["beta_jobs_dates_converted"] = True
        except Exception as e:
            logger.error("Beta opt-in repair failed for %s: %s", write_owner_id, e, exc_info=True)
            raise HTTPException(status_code=500,
                                detail="Couldn't prepare your jobs. Nothing was switched — please try again.")

    meta["beta_jobs"] = data.enabled
    # The whole dict, read back first: whether the admin API merges or replaces
    # user_metadata, the Terms acceptance and display name next to this flag
    # survive either way.
    client.auth.admin.update_user_by_id(user_id, {"user_metadata": meta})
    return {"beta_jobs": data.enabled, "report": report}


# ── Job defaults ─────────────────────────────────────────────────────────────
#
# What every new job starts with: per diem a day for shoot and other days, and
# how it's paid. Account-wide, so it's the shared account's (write_owner_id)
# metadata a team member reads and writes. user_metadata is browser-writable,
# so services/job_rates.clean_defaults re-checks it before it reaches a job.


def job_defaults_for(client, owner_id: str) -> dict:
    """Never raises: a new job is never held up by its defaults."""
    try:
        return clean_defaults(_metadata(client, owner_id).get("job_defaults"))
    except Exception as e:
        logger.error("Reading job defaults for %s failed: %s", owner_id, e, exc_info=True)
        return clean_defaults(None)


@router.get("/account/job-defaults")
def get_job_defaults(write_owner_id: str = Depends(get_write_owner_id)):
    return job_defaults_for(get_client(), write_owner_id)


@router.put("/account/job-defaults")
def set_job_defaults(data: JobDefaults, write_owner_id: str = Depends(get_write_owner_id)):
    client = get_client()
    meta = _metadata(client, write_owner_id)
    meta["job_defaults"] = clean_defaults(data.model_dump())
    client.auth.admin.update_user_by_id(write_owner_id, {"user_metadata": meta})
    return meta["job_defaults"]
