"""The client-facing Production Reconciliation statement (docs/estimate-
reconcile-plan.md, PR 4; handoff §8). Pure: the figures come from
services/budget.py, the layout from templates/reconciliation_statement.html.j2.

What it is: the job as shot, against the signed estimate, so scope changes are
on record before the final invoice. "This statement is not an invoice."

Two columns only — Estimated and This project. NO variance column: it invites
line-by-line negotiation on the few lines that went up, when the story is that
the total went down. Reasons are the producer's own notes, in grey under the
line. "This project" is what the line BILLS (budget.projected: open lines land
on their estimate), never what it cost:

⚠️ A CLIENT DOCUMENT. Nothing about cost, margin or profit reaches it — a
Fixed line's actual cost is the producer's business, and printing it would
hand the client her margin line by line. tests/test_reconciliation_statement.py
asserts no line's cost appears. A Fixed line nobody quoted (an absorbed cost)
bills nothing and is left off; so is a floor line zeroed on purpose.

⚠️ ASCII marks only in what this module and its template write (WeasyPrint's
fonts vary by machine); what the producer typed prints as typed.
"""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.budget import projected

_MAX_TEXT = 2000


def amount(cents: int | None) -> str:
    """12,000.00 / -113.58 — the statement's figures, no currency mark, ASCII."""
    if cents is None:
        return "-"
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(int(cents)), 100)
    return f"{sign}{whole:,}.{part:02d}"


def long_date(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def settings(job: dict) -> dict:
    """What only the statement says (jobs.statement, supabase/statement.sql)."""
    s = job.get("statement") or {}
    out = {k: (s.get(k) or "").strip()[:_MAX_TEXT] for k in ("client_contact", "estimate_ref", "intro")}
    return out


def contact_lines(statement: dict) -> list[str]:
    """The client block: her typed contact lines, then the job's client."""
    lines = [ln.strip() for ln in statement["settings"]["client_contact"].splitlines() if ln.strip()]
    if statement["client_name"] and statement["client_name"] not in lines:
        lines.append(statement["client_name"])
    return lines or ["-"]


def _default_note(line: dict) -> str:
    """A reason when she hasn't written one — only where the paper would
    otherwise leave the client guessing."""
    if line.get("dropped"):
        return "Not shot"
    if line.get("bucket") == "pass":
        if line.get("act_open"):
            return "At estimate until the final figure is in"
        if line.get("act_cents") is not None:
            return "Trued up to actual" if line.get("act_cents") != line.get("est_cents") else ""
        return "At estimate until the final figure is in"
    return ""


def _shown(line: dict, billing: int) -> bool:
    est = line.get("est_cents")
    return bool(est) or billing != 0


def build(job: dict, lines: list[dict], invoices: list[dict], producer: dict,
          production_dates: str, statement_on: str) -> dict:
    """Everything the template prints. `lines` already carry any receipts'
    sums as their actuals (budget.with_expenses), in estimate order."""
    sections: list[dict] = []
    by_name: dict = {}
    original = revised = 0
    for line in lines:
        billing, _ = projected(line)
        original += line.get("est_cents") or 0
        revised += billing
        if not _shown(line, billing):
            continue
        name = (line.get("section") or "").strip() or None
        if name not in by_name:
            by_name[name] = {"name": name, "rows": [], "est": 0, "project": 0}
            sections.append(by_name[name])
        s = by_name[name]
        block = (line.get("block") or "").strip()
        if block and (block.lower() in (name or "").lower() or block.lower() in (line.get("name") or "").lower()):
            block = ""                        # the heading or the line already says which market
        s["rows"].append({"name": line.get("name") or "", "block": block,
                          "note": (line.get("note") or "").strip() or _default_note(line),
                          "est": line.get("est_cents"), "project": billing, "dropped": bool(line.get("dropped"))})
        s["est"] += line.get("est_cents") or 0
        s["project"] += billing

    for s in sections:
        # Itemize when the number changed, summarize when it didn't (handoff
        # §8): a section where nothing was shot is one line, as it was sent.
        if len(s["rows"]) > 1 and all(r["dropped"] for r in s["rows"]):
            s["rows"] = [{"name": ", ".join(r["name"] for r in s["rows"]), "block": "", "note": "Not shot",
                          "est": s["est"], "project": 0, "dropped": True}]

    inv = [{"label": i.get("label") or "Invoice", "amount": int(i.get("amount_cents") or 0),
            "issued_on": i.get("issued_on"), "paid": bool(i.get("paid")), "paid_on": i.get("paid_on")}
           for i in invoices]
    invoiced = sum(i["amount"] for i in inv)
    return {
        "job_name": job.get("name") or "", "client_name": job.get("client_name") or "",
        "producer": {"name": producer.get("name") or "", "email": producer.get("email") or "",
                     "phone": (job.get("producer_phone") or "").strip()},
        "settings": settings(job), "production_dates": production_dates, "statement_on": statement_on,
        "sections": sections, "original": original, "revised": revised, "change": revised - original,
        "invoices": inv, "invoiced": invoiced, "balance": revised - invoiced,
    }


_env: Environment | None = None


def _environment() -> Environment:
    global _env
    if _env is None:
        _env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                           autoescape=select_autoescape(["html", "j2", "html.j2"], default=True),
                           trim_blocks=True, lstrip_blocks=True)
        _env.filters["amount"] = amount
        _env.filters["long_date"] = long_date
    return _env


def to_html(statement: dict) -> str:
    return _environment().get_template("reconciliation_statement.html.j2").render(s=statement,
                                                                                contact=contact_lines(statement))


def filename(statement: dict) -> str:
    return f"Production Reconciliation - {statement['job_name'] or 'Job'}"
