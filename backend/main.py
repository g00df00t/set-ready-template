import logging
import os
import time
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from routers import projects, crew, schedule, call_sheet, contacts, talent, roster, company_moves, location_roster, support, account, waitlist, attachments, admin, wrap_report, deal_memo, brand, jobs, rooming, per_diem, holds, travel, talent_call_sheet, vendors, job_info, budget, pc_log, receipts, estimate_import, setup
from config import settings
from rate_limit import limiter
from database import get_client

# Default to INFO so DEBUG traces (which carry shoot addresses/coordinates) stay
# out of prod logs; set LOG_LEVEL=DEBUG locally to see them.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

# Error monitoring (opt-in): set SENTRY_DSN to capture 5xx responses and
# unhandled exceptions in production. No-op when unset; PII is not sent.
if settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(dsn=settings.sentry_dsn, send_default_pii=False)

# A producer's own copy is a public server run by someone who won't read an
# API explorer; it doesn't need to advertise one.
app = FastAPI(title="SET>READY API", version="1.0.0",
              docs_url=None if settings.single_owner else "/docs",
              redoc_url=None if settings.single_owner else "/redoc")

# Per-IP rate limiting for the public, unauthenticated endpoints (see rate_limit.py).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return `detail` as a plain string.

    The frontend renders `detail` directly and JSON-stringifies anything that
    isn't a string, so FastAPI's default error list reaches the user as a blob.
    """
    errors = exc.errors()
    message = errors[0].get("msg", "Invalid request") if errors else "Invalid request"
    # Pydantic prefixes messages raised from a custom validator.
    message = message.removeprefix("Value error, ")
    return JSONResponse(status_code=422, content={"detail": message})


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    # Preview deployments get a fresh hostname per push, so an exact list can only
    # ever cover whichever alias was remembered. The regex covers the rest; it is
    # applied with re.fullmatch, so a pattern can't be satisfied by a prefix.
    # None rather than "" when unset: an empty pattern fullmatches nothing, but
    # passing it would still compile a regex on every request for no reason.
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Browsers hide every response header from cross-origin JS except a short
    # safelist. Without naming it here, the PDF download can read the bytes but
    # not the filename the server chose, and every sheet saves as "download".
    expose_headers=["Content-Disposition"],
)

@app.api_route("/health", methods=["GET", "HEAD"])
@limiter.limit("120/minute")
def health(request: Request):
    """Liveness + database reachability, for an external monitor.

    Exists because the failure that actually costs a producer their shoot day is
    the quiet one: the app answers fine while Supabase is unreachable, so every
    page loads empty and nothing looks broken. A monitor that only checks "does
    the process respond" reports green through exactly that outage. So this
    endpoint does a real round trip to the database and fails loudly when it
    can't — 503 is what a monitor should page on.

    Deliberately public and deliberately empty: it names no table, returns no
    count, and exposes nothing about the data. It reads one id from usage_events,
    which holds no PII, and throws it away — the point is that a query completed,
    not what came back.

    HEAD as well as GET, because monitors probe with HEAD first. FastAPI routes
    don't answer HEAD automatically the way a plain Starlette route does, so
    @app.get alone returned 405 to that probe — UptimeRobot then retried with GET
    and passed, which is why this never showed up as an outage, only as a 405 in
    the logs next to every successful check. The database round trip still runs
    on a HEAD, so a 503 still reaches a monitor that only reads status codes;
    only the body is dropped.
    """
    started = time.monotonic()
    try:
        get_client().table("usage_events").select("id").limit(1).execute()
    except Exception as e:
        logger.warning("health check: database unreachable: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable"},
        )
    return {
        "status": "ok",
        "database": "ok",
        "db_ms": round((time.monotonic() - started) * 1000),
    }


app.include_router(projects.router, prefix="/api")
app.include_router(crew.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(call_sheet.router, prefix="/api")
app.include_router(contacts.router, prefix="/api")
app.include_router(talent.router, prefix="/api")
app.include_router(roster.router, prefix="/api")
app.include_router(company_moves.router, prefix="/api")
app.include_router(location_roster.router, prefix="/api")
app.include_router(support.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(waitlist.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(wrap_report.router, prefix="/api")
app.include_router(brand.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(deal_memo.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(rooming.router, prefix="/api")
app.include_router(per_diem.router, prefix="/api")
app.include_router(holds.router, prefix="/api")
app.include_router(travel.router, prefix="/api")
app.include_router(talent_call_sheet.router, prefix="/api")
app.include_router(vendors.router, prefix="/api")
app.include_router(job_info.router, prefix="/api")
app.include_router(budget.router, prefix="/api")
app.include_router(pc_log.router, prefix="/api")
app.include_router(receipts.router, prefix="/api")
app.include_router(estimate_import.router, prefix="/api")
app.include_router(setup.router, prefix="/api")
