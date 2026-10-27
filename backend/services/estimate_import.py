"""Reading an estimate into draft budget lines (docs/estimate-reconcile-plan.md,
PR 2). Same shape as reading a receipt (services/receipt_import.py):

1. `prepare` — refuse anything that isn't a PDF or an Excel workbook BEFORE it
   costs a model call. The leading bytes decide, never the filename. A PDF goes
   to the model as itself; a workbook's cells are turned into text here (a
   model can't take an .xlsx), after a zip-bomb check.
2. `claude_service.parse_estimate` — the model drafts the lines, with a basis
   for each: Fee / Fixed / At cost. No estimate says it; the model suggests,
   the producer confirms. That's the moment the basis gets recorded
   (handoff §5).
3. `clean` — trust nothing about what comes back. Amounts become exact cents
   or the line is dropped; a qty × rate is kept only when it comes to the
   printed amount to the cent (the amount wins, always); basis, floor kind and
   markup are checked against what the budget accepts; text is bounded. The
   printed grand total is checked against the lines' sum, and a mismatch is
   shown, never hidden.

Nothing here logs what an estimate says. Tested only with a fabricated
estimate (tests/fixtures/fabricated_estimate.*) — staging shares production's
Anthropic key.
"""

import io
import zipfile
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from services import claude_service
from services.attachment_service import human_size
from services.budget import BUCKETS, FLOOR_KINDS, estimate_amount, hundredths
from services.receipt_import import Rejected, _text, to_cents

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 12
MAX_LINES = 200                       # a job holds 500 budget lines
MAX_UNZIPPED = 60 * 1024 * 1024       # a real workbook is a few MB once unzipped
MAX_SHEETS = 10
MAX_ROWS = 1500                       # per sheet
MAX_TEXT = 120_000                    # characters of cells sent to the model
MAX_QTY_HUNDREDTHS = 10_000_000       # numeric(8,2)

PDF, XLSX = "application/pdf", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"     # .xls, .doc: the old binary formats


def sniff(data: bytes) -> str | None:
    """What the bytes say: a PDF, a workbook, or something with a name."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(_OLE):
        return "ole"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            return None
        if "xl/workbook.xml" in names:
            return XLSX
        if "word/document.xml" in names:
            return "docx"
        if "ppt/presentation.xml" in names or "content.xml" in names:
            return "other_office"
    return None


def workbook_text(data: bytes) -> str:
    """A workbook's cells as text, one row per line, " | " between cells.
    Formulas read as the value Excel last saved with them."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED:
        raise Rejected("That spreadsheet is too big to read. Save the estimate as a PDF and try that.", status=413)
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise Rejected("That spreadsheet couldn't be opened — it may be damaged.")
    out = []
    try:
        for ws in wb.worksheets[:MAX_SHEETS]:
            rows = []
            for row in ws.iter_rows(max_row=MAX_ROWS, values_only=True):
                cells = [_cell(v) for v in row]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                out.append(f"## Sheet: {ws.title}\n" + "\n".join(rows))
    finally:
        wb.close()
    text = "\n\n".join(out)
    if not text.strip():
        raise Rejected("That spreadsheet is empty.")
    if len(text) > MAX_TEXT:
        raise Rejected("That spreadsheet holds more than an estimate does. Save just the estimate as a PDF and try that.",
                       status=413)
    return text


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return " ".join(str(v).split())[:300]


def prepare(data: bytes) -> tuple[bytes | None, str | None]:
    """(the PDF to send, None) or (None, a workbook's text) — or Rejected."""
    if not data:
        raise Rejected("That file came through empty.")
    if len(data) > MAX_BYTES:
        raise Rejected(f"That file is {human_size(len(data))}. An estimate can be up to {human_size(MAX_BYTES)}.", status=413)
    kind = sniff(data)
    if kind == PDF:
        _check_pdf_pages(data)
        return data, None
    if kind == XLSX:
        return None, workbook_text(data)
    if kind == "ole":
        raise Rejected("That's an older Excel or Word file. Save it as .xlsx, or as a PDF, and try again.", status=415)
    if kind in ("docx", "other_office"):
        raise Rejected("That's a document, not a PDF. Export it as a PDF (File → Save as PDF) and try again.", status=415)
    raise Rejected("An estimate can be a PDF or an Excel (.xlsx) file.", status=415)


def _check_pdf_pages(data: bytes) -> None:
    """receipt_import's damage and password checks, with an estimate's page cap."""
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise Rejected("That PDF couldn't be opened — it may be damaged.")
    with doc:
        if doc.needs_pass:
            raise Rejected("That PDF is password-protected. Remove the password and try again.")
        if doc.page_count < 1:
            raise Rejected("That PDF has no pages in it.")
        if doc.page_count > MAX_PAGES:
            raise Rejected(f"That PDF is {doc.page_count} pages long. An estimate can be up to {MAX_PAGES} pages.")


# ── What comes back ──────────────────────────────────────────────────────────

def _qty(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    h = hundredths(str(value).replace(",", "").strip())
    if h is None or h <= 0 or h > MAX_QTY_HUNDREDTHS:
        return None
    return h / 100


def _markup_bp(value) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        bp = int((Decimal(str(value).replace("%", "").strip()) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return 0
    return bp if 0 < bp <= 10_000 else 0


def clean(raw) -> dict:
    """The model's answer as draft lines plus the total check.

    Raises ValueError when the answer isn't the object asked for — a failed
    read, which the producer should hear as different from "nothing found".
    """
    if isinstance(raw, list):                 # just the lines: accept it, no total to check
        raw = {"lines": raw, "total": None}
    if not isinstance(raw, dict) or not isinstance(raw.get("lines"), list):
        raise ValueError("expected an object with a list of lines")

    lines, skipped, floors = [], 0, set()
    for item in raw["lines"]:
        if len(lines) >= MAX_LINES:
            skipped += 1
            continue
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        amount = to_cents(item.get("amount"))
        qty, rate = _qty(item.get("qty")), to_cents(item.get("rate"))
        if rate is not None and rate <= 0:
            rate = None
        worked = estimate_amount(qty, rate)
        if amount is None and worked is not None:
            amount = worked
        if not name or amount is None or amount <= 0:
            skipped += 1                      # a discount, a TBD, a heading read as a line
            continue
        if worked != amount:
            qty, rate = None, None            # the printed amount wins; a qty × rate that disagrees goes
        basis = item.get("basis") if item.get("basis") in BUCKETS else "rate"
        floor = item.get("floor") if item.get("floor") in FLOOR_KINDS and item.get("floor") not in floors else None
        if floor:
            floors.add(floor)
            basis = "fee"
        lines.append({
            "section": (_text(item.get("section")) or "")[:120] or None,
            "name": name,
            "block": (_text(item.get("market")) or "")[:80] or None,
            "qty": qty,
            "unit_amount_cents": rate if qty is not None else None,
            "est_cents": amount,
            "bucket": basis,
            "basis_reason": (_text(item.get("basis_reason")) or "")[:120] or None,
            "floor_kind": floor,
            "markup_bp": _markup_bp(item.get("markup_pct")) if basis == "pass" else 0,
        })

    stated = to_cents(raw.get("total"))
    stated = stated if stated is not None and stated > 0 else None
    summed = sum(ln["est_cents"] for ln in lines)
    return {"lines": lines, "skipped": skipped,
            "total_check": {"stated_cents": stated, "lines_cents": summed,
                            "matches": None if stated is None else stated == summed}}


def read_estimate(data: bytes, on_usage: claude_service.UsageCallback = None) -> dict:
    """Check, read, clean. Blocking — the router runs it in a thread. A refused
    file never reaches the model, so `on_usage` is never called for one."""
    pdf, text = prepare(data)
    return clean(claude_service.parse_estimate(pdf, text, on_usage))
