"""The producer's PC log: the reconciliation cover sheet, one line per receipt, in the
category breakdown the client wants (docs/producer-documents-map.md §1.10). Pure.

Her sheet, column for column:

    # · DATE · TO WHOM PAID · FOR WHAT · TOTAL · <the nine categories>

and its footer:

    TOTAL FEES AND EXPENSES        a sum per column
    PRODUCTION FEE %               8% of that total (the producer, Q6: fees AND expenses)
    GRAND TOTAL                    total + fee
    LESS ADVANCE RECEIVED          what the client has paid (paid invoices)
    DIFFERENCE                     grand total − advance: what's still owed

Money is integer cents; the fee is basis points (800 = 8%), applied ONCE to the
total and rounded half-up, exactly as her sheet's single formula does — never
per line or per column, which would drift by a cent here and there.

TWO KINDS OF LINE (Patrick, 2026-10-02):
- an expense she typed or a receipt (job_expenses), and
- a GENERATED line, worked out from what the job already holds: each booked
  person's fee (their rates × their days), the per diem total, and every
  vendor payment with an amount. Generated lines are LIVE — they follow the
  job — until the log is MARKED SENT. Sending freezes a copy
  (job_pc_log_sends); after that a source change is FLAGGED against the copy,
  never applied to it silently, because a sent PC log is what the client pays
  against and must be reproducible.
A generated line can be hidden, re-amounted or re-categorised by hand
(jobs.pc_log_generated, keyed by the line's source); a hand amount is marked.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from services.budget import advance_received, round_div
from services.holds import is_booked
from services.job_dates import date_span, hire_base, person_days

# Her legend, in her column order. The first seven are by department, so a
# hire's department can default a line's category.
CATEGORIES = {
    "photography": "Photography",
    "video": "Video",
    "talent": "Talent",
    "stylist_hmu": "Stylist/HMU",
    "art_props": "Art Dept/Props",
    "location_studio": "Location/Studio",
    "production_misc": "Production/Misc",
    "producer": "Producer",
    "payroll_fee": "Payroll Service Fee",
}
LEGEND = {
    "photography": "Photo team fees and their related expenses",
    "video": "Video team fees and their related expenses",
    "talent": "Fees and their related expenses",
    "stylist_hmu": "All stylist and HMU fees and their related expenses",
    "art_props": "All fees and related prop expenses",
    "location_studio": "Location and studio crew fees and related expenses",
    "production_misc": "All remaining costs: equipment rental, hotel, catering, flights",
    "producer": "Producer fee only",
    "payroll_fee": "The payroll provider's fee",
}
DEFAULT_FEE_BP = 800
CAMERA_CHOICES = ("photography", "video")
MAX_CENTS = 1_000_000_000

# Which rate a day of each type is paid at (Patrick, 2026-10-02, after the producer's
# answers): a down day is ½ the shoot rate, a check-in day is unpaid, and a
# WRAP day — packing up, shipping back — is paid like prep. A date with two
# types is paid ONCE, at the first of these that applies.
PAY_ORDER = ("shoot", "prep", "wrap", "travel", "travel_out", "off", "checkin")
PAY_RATE = {"shoot": "rate_shoot", "prep": "rate_prep", "wrap": "rate_prep",
            "travel": "rate_travel", "travel_out": "rate_travel", "off": "rate_shoot", "checkin": None}
PAY_WORD = {"shoot": "shoot", "prep": "prep", "wrap": "wrap", "travel": "travel",
            "travel_out": "travel", "off": "down", "checkin": "check-in"}

# Vendor bookings: what kind goes in which column. A location or its permit is
# Location/Studio; the hotel, motorhome, rentals and the rest are
# Production/Misc ("equipment rental, hotel, catering, flights").
VENDOR_CATEGORY = {"location": "location_studio", "permit": "location_studio"}
VENDOR_STEP_WORDS = {"deposit": "Deposit", "final_bill": "Final bill (balance)"}


def to_cents(value) -> int | None:
    """A stored dollar amount (numeric, float or string) as exact cents."""
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    if d < 0:
        return None
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dollars(cents: int | None) -> str:
    """$1,234.56 — always two places on a ledger. ASCII only (it reaches PDFs)."""
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{part:02d}"


# ── Which column a person's fee goes in ─────────────────────────────────────

_RULES = (
    (r"styl|wardrobe|costume|hair|make-?up|\bhmu\b|groom", "stylist_hmu"),
    (r"\bart\b|prop|set dec", "art_props"),
    (r"location|studio", "location_studio"),
    (r"sound|audio|boom|mixer", "video"),
    (r"video|cinemat|\bdp\b|director of photography", "video"),   # before "photo": a DP is video
    (r"photo|still", "photography"),
    (r"camera|grip|electric|gaffer|lighting|\bdit\b|digital tech", "camera"),
)


def category_for_hire(hire: dict, camera: str = "photography") -> str:
    """Talent → Talent. Otherwise read the department (then the role) against
    her legend; the camera team — camera, grip & electric, lighting — bills as
    the job's choice of Photography or Video. Anything else is Production/Misc.
    Always a default: any line can be moved by hand."""
    if hire.get("kind") == "talent":
        return "talent"
    for text in (hire.get("department"), hire.get("role")):
        t = (text or "").lower()
        for pattern, cat in _RULES:
            if t and re.search(pattern, t):
                return camera if cat == "camera" else cat
    return "production_misc"


# ── Generated lines ─────────────────────────────────────────────────────────

def hire_fee(job: dict, hire: dict) -> dict:
    """What one booked person is owed: each of their dates paid once at its
    type's rate. {amount_cents, last_date, detail, missing} — `missing` names
    the day types worked with no rate set, so the line says so instead of
    quietly reading $0."""
    days = person_days(hire_base(job, hire), hire.get("dates_override"))
    counts: dict[str, int] = {}
    for d in days:
        t = next((t for t in PAY_ORDER if t in d["types"]), None)
        if t:
            counts[t] = counts.get(t, 0) + 1
    total, missing = 0, []
    parts: dict[tuple[str, int], int] = {}      # (word, rate) → days; travel in + out read as one
    for t in PAY_ORDER:
        n = counts.get(t)
        if not n or PAY_RATE[t] is None:
            continue
        rate = to_cents(hire.get(PAY_RATE[t]))
        if rate is None:
            missing.append(PAY_WORD[t])
            continue
        if t == "off":
            rate = round_div(rate, 2)
        total += n * rate
        parts[(PAY_WORD[t], rate)] = parts.get((PAY_WORD[t], rate), 0) + n
    detail = " + ".join(f"{n} {word} x {dollars(rate)}" for (word, rate), n in parts.items())
    pct = hire.get("agency_fee_pct")
    if hire.get("kind") == "talent" and pct not in (None, "") and float(pct) > 0 and total:
        bp = int((Decimal(str(pct)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        fee = round_div(total * bp, 10_000)
        total += fee
        detail += f" + {Decimal(str(pct)).normalize():f}% agency fee"
    return {"amount_cents": total, "last_date": days[-1]["date"] if days else None,
            "detail": detail, "missing": sorted(set(missing))}


def generated_lines(job: dict, hires: list[dict], vendors: list[dict], per_diem_sheet: dict | None) -> list[dict]:
    """Every line the job already knows about, before any hand changes.

    `vendors` are services/vendors.resolve()'s output (titles filled in);
    `per_diem_sheet` is services/per_diem.build_sheet()'s."""
    camera = job.get("pc_log_camera") if job.get("pc_log_camera") in CAMERA_CHOICES else "photography"
    out = []
    for h in hires:
        if not is_booked(h):
            continue
        fee = hire_fee(job, h)
        if not fee["amount_cents"] and not fee["missing"]:
            continue            # no paid days at all
        what = " - ".join(x for x in (h.get("role"), fee["detail"]) if x)
        out.append({"key": f"hire:{h['id']}", "source": "talent" if h.get("kind") == "talent" else "crew",
                    "spent_on": fee["last_date"], "payee": h.get("name") or "", "description": what,
                    "amount_cents": fee["amount_cents"], "category": category_for_hire(h, camera),
                    "missing_rates": fee["missing"]})

    if per_diem_sheet and per_diem_sheet.get("rows"):
        total = sum(to_cents(r["total"]) or 0 for r in per_diem_sheet["rows"])
        dates = [c["date"] for c in per_diem_sheet.get("dates") or []]
        n = len(per_diem_sheet["rows"])
        out.append({"key": "per_diem", "source": "per_diem", "spent_on": dates[-1] if dates else None,
                    "payee": "Crew per diem", "description": f"Per diem, {n} {'person' if n == 1 else 'people'}",
                    "amount_cents": total, "category": "production_misc", "missing_rates": []})

    for v in vendors:
        if v.get("broken"):
            continue
        for step, word in VENDOR_STEP_WORDS.items():
            s = (v.get("steps") or {}).get(step) or {}
            amount = to_cents(s.get("amount"))
            if not amount:
                continue
            out.append({"key": f"vendor:{v['id']}:{step}", "source": "vendor", "spent_on": s.get("date"),
                        "payee": v.get("title") or "", "description": f"{v.get('kind_label') or 'Vendor'} - {word}",
                        "amount_cents": amount, "category": VENDOR_CATEGORY.get(v.get("kind"), "production_misc"),
                        "missing_rates": []})
    return out


KEY_RE = re.compile(r"^(hire:[\w-]+|per_diem|vendor:[\w-]+:(deposit|final_bill))$")


def validate_override(key: str, value) -> dict | None:
    """One generated line's hand changes: {hidden, amount_cents, category}.
    Nothing left to say → None (the entry is removed)."""
    if not KEY_RE.match(key or ""):
        raise ValueError("That isn't a generated line.")
    if not isinstance(value, dict):
        raise ValueError("A line's changes must be an object.")
    out = {}
    if value.get("hidden"):
        out["hidden"] = True
    amount = value.get("amount_cents")
    if amount is not None:
        if not isinstance(amount, int) or isinstance(amount, bool) or not 0 <= amount <= MAX_CENTS:
            raise ValueError("An amount must be whole cents between 0 and $10,000,000.")
        out["amount_cents"] = amount
    cat = value.get("category")
    if cat is not None:
        if cat not in CATEGORIES:
            raise ValueError("Pick one of the PC log's columns.")
        out["category"] = cat
    return out or None


def apply_overrides(lines: list[dict], overrides: dict) -> list[dict]:
    """Generated lines with their hand changes on top. The worked-out amount
    and column stay alongside, so the screen can show what was changed and
    put it back."""
    out = []
    for line in lines:
        o = (overrides or {}).get(line["key"]) or {}
        out.append({**line, "generated": True, "hidden": bool(o.get("hidden")),
                    "generated_amount_cents": line["amount_cents"], "generated_category": line["category"],
                    "amount_cents": o.get("amount_cents", line["amount_cents"]),
                    "category": o.get("category", line["category"]),
                    "amount_overridden": "amount_cents" in o, "category_overridden": "category" in o})
    return out


def expense_lines(expenses: list[dict]) -> list[dict]:
    return [{"key": f"expense:{e['id']}", "source": "expense", "expense_id": e["id"],
             "budget_line_id": e.get("budget_line_id"), "spent_on": e.get("spent_on"),
             "payee": e.get("payee") or "", "description": e.get("description") or "",
             "amount_cents": int(e["amount_cents"]), "category": e["category"], "generated": False,
             "hidden": False, "missing_rates": [],
             "has_receipt": bool(e.get("receipt_path")), "receipt_name": e.get("receipt_name")}
            for e in expenses]


def _order(rows: list[dict]) -> list[dict]:
    """Date order, as she'd write them in; undated at the end. Then numbered."""
    rows = sorted(rows, key=lambda r: (r.get("spent_on") is None, str(r.get("spent_on") or ""),
                                       not r.get("generated"), r["payee"].lower(), r["key"]))
    n = 0
    out = []
    for r in rows:
        if not r.get("hidden"):
            n += 1
        out.append({**r, "number": n if not r.get("hidden") else None})
    return out


def _span_text(first: str | None, last: str | None) -> str:
    if not first:
        return ""
    a, b = date.fromisoformat(first), date.fromisoformat(last or first)
    if a == b:
        return f"{a.strftime('%b')} {a.day}, {a.year}"
    if a.year == b.year:
        return f"{a.strftime('%b')} {a.day} - {b.strftime('%b')} {b.day}, {b.year}"
    return f"{a.strftime('%b')} {a.day}, {a.year} - {b.strftime('%b')} {b.day}, {b.year}"


def header(job: dict, day_dates: list[str], producer: str | None) -> dict:
    span = date_span(job.get("crew_dates"), day_dates)
    return {"job_name": job.get("name") or "", "client": job.get("client_name") or "",
            "producer": producer or "", "project_dates": _span_text(*(span or (None, None)))}


def build_log(job: dict, generated: list[dict], expenses: list[dict], invoices: list[dict],
              hdr: dict) -> dict:
    """The live log: every row (hidden ones included, unnumbered, so the
    screen can offer them back), the header and the footer."""
    fee_bp = job.get("production_fee_bp")
    fee_bp = DEFAULT_FEE_BP if fee_bp is None else int(fee_bp)
    rows = _order(apply_overrides(generated, job.get("pc_log_generated") or {}) + expense_lines(expenses))
    return {"header": hdr, "rows": rows, "totals": totals(rows, fee_bp, invoices)}


def totals(rows: list[dict], fee_bp: int, invoices: list[dict]) -> dict:
    """The footer for a set of PC log rows ({amount_cents, category}).
    Rows marked `hidden` are left out — a generated line the producer took
    off the log."""
    shown = [r for r in rows if not r.get("hidden")]
    by_category = {k: 0 for k in CATEGORIES}
    for r in shown:
        by_category[r["category"]] += int(r["amount_cents"])
    total = sum(by_category.values())
    fee = round_div(total * fee_bp, 10_000)
    advance = advance_received(invoices)
    return {"by_category": by_category, "total_cents": total, "fee_bp": fee_bp,
            "fee_cents": fee, "grand_total_cents": total + fee,
            "advance_cents": advance, "difference_cents": total + fee - advance}


# ── Mark as sent ─────────────────────────────────────────────────────────────

SNAPSHOT_FIELDS = ("key", "number", "spent_on", "payee", "description", "amount_cents", "category", "source")


def snapshot(log: dict, sent_on: str) -> dict:
    """What "Mark as sent" freezes: the header, the rows that were ON the log
    (hidden ones weren't), and the footer — everything an export prints."""
    return {"sent_on": sent_on, "header": log["header"],
            "rows": [{k: r.get(k) for k in SNAPSHOT_FIELDS} for r in log["rows"] if not r.get("hidden")],
            "totals": log["totals"]}


def changes_since(sent: dict, log: dict) -> list[dict]:
    """How the live log differs from the copy that was sent, line by line:
    added, removed, or changed (amount, column, date, payee or description).
    Flagged, never applied — the sent copy stays what was sent."""
    then = {r["key"]: r for r in sent.get("rows") or []}
    now = {r["key"]: r for r in log["rows"] if not r.get("hidden")}
    out = []
    for key, r in now.items():
        if key not in then:
            out.append({"key": key, "change": "added", "payee": r["payee"], "description": r["description"],
                        "now_cents": r["amount_cents"]})
    for key, r in then.items():
        if key not in now:
            out.append({"key": key, "change": "removed", "payee": r["payee"], "description": r["description"],
                        "then_cents": r["amount_cents"]})
            continue
        n = now[key]
        what = [f for f in ("amount_cents", "category", "spent_on", "payee", "description") if r.get(f) != n.get(f)]
        if what:
            out.append({"key": key, "change": "changed", "fields": what, "payee": n["payee"],
                        "description": n["description"], "then_cents": r["amount_cents"],
                        "now_cents": n["amount_cents"]})
    t0, t1 = sent.get("totals") or {}, log["totals"]
    if t0.get("fee_bp") != t1["fee_bp"]:
        out.append({"key": "fee", "change": "changed", "fields": ["fee_bp"], "payee": "",
                    "description": "Production fee %", "then_cents": t0.get("fee_cents"), "now_cents": t1["fee_cents"]})
    if t0.get("advance_cents") != t1["advance_cents"]:
        out.append({"key": "advance", "change": "changed", "fields": ["advance_cents"], "payee": "",
                    "description": "Advance received", "then_cents": t0.get("advance_cents"),
                    "now_cents": t1["advance_cents"]})
    return out

