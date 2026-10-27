"""Reading a receipt into PC log lines (build order #8, PR 3).

A photo of a receipt, a screenshot or a PDF goes in; draft lines come out —
date, to whom paid, for what, amount, which of her nine columns — for the
producer to check on the PC log before any of them is added. Same pattern as
the call sheet PDF import (services/call_sheet_import.py):

1. `prepare` — refuse anything that isn't a small image or a short PDF BEFORE
   it costs a model call. The leading bytes decide, never the filename or the
   Content-Type the browser claimed. Photos are shrunk (a phone shot is 4–8 MB;
   a receipt stays legible at 2000 px) and that smaller copy is both what the
   model reads and what's kept.
2. `claude_service.parse_receipt` — the model reads the file itself.
3. `clean_lines` — trust nothing about what comes back: an amount becomes
   exact cents or the line is dropped, a date must be a real date, the column
   must be one of hers, text is bounded, and anything that looks like a card or
   account number is cut.

Nothing here logs what a receipt says. Tested only with fabricated receipts
(tests/fixtures/fabricated_receipt.*) — staging shares production's Anthropic
key, so a real receipt sent from staging is a real model call on real data.
"""

import io
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from services import claude_service
from services.attachment_service import human_size
from services.pc_log import CATEGORIES, LEGEND, MAX_CENTS

MAX_BYTES = 15 * 1024 * 1024        # what's accepted; photos are shrunk well below this
MAX_PAGES = 5
MAX_DIMENSION = 2000                # px, longest side, for a photo
MAX_LINES = 40                      # a statement read into many purchases
_MAX_FIELD = 200

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
EXTENSIONS = {**IMAGE_TYPES, "application/pdf": ".pdf"}


class Rejected(ValueError):
    """Refused, with a message for the producer and the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def sniff(data: bytes) -> str | None:
    """The content type the bytes themselves say, or None."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"heif", b"mif1", b"msf1", b"hevc"):
        return "image/heic"
    return None


def _check_pdf(data: bytes) -> None:
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
            raise Rejected(f"That PDF is {doc.page_count} pages long. A receipt can be up to {MAX_PAGES} pages.")


def _shrink_photo(data: bytes, media_type: str) -> tuple[bytes, str]:
    """A legible copy at most MAX_DIMENSION px on its longest side, as JPEG.
    Transparency is flattened onto white — a receipt has no use for it."""
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)        # a phone photo taken sideways reads upright
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            plate = Image.new("RGB", img.size, (255, 255, 255))
            plate.paste(img, mask=img.split()[-1])
            img = plate
        else:
            img = img.convert("RGB")
        if max(img.size) > MAX_DIMENSION:
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)
    except Exception:
        raise Rejected("That image couldn't be opened — it may be damaged.")
    shrunk = out.getvalue()
    # A small PNG screenshot can be smaller than its JPEG: keep whichever is.
    return (shrunk, "image/jpeg") if len(shrunk) < len(data) or media_type == "image/gif" else (data, media_type)


def prepare(data: bytes) -> tuple[bytes, str]:
    """(the bytes to read and keep, their content type), or Rejected."""
    if not data:
        raise Rejected("That file came through empty.")
    if len(data) > MAX_BYTES:
        raise Rejected(f"That file is {human_size(len(data))}. A receipt can be up to {human_size(MAX_BYTES)}.", status=413)
    kind = sniff(data)
    if kind == "image/heic":
        raise Rejected("That's an iPhone HEIC photo. Save it as a JPEG (or take a screenshot of it) and try again.", status=415)
    if kind is None:
        raise Rejected("That isn't a photo or a PDF. Receipts can be JPEG, PNG, WEBP, GIF or PDF.", status=415)
    if kind == "application/pdf":
        _check_pdf(data)
        return data, kind
    return _shrink_photo(data, kind)


_PATH = re.compile(r"^(?P<job>[0-9a-f-]{36})/[0-9a-f-]{36}\.(?:jpg|png|webp|gif|pdf)$")


def valid_path(job_id, path: str | None) -> bool:
    """A receipt path this job may name: its own folder, our own file names —
    so a line can never be pointed at another job's receipt."""
    m = _PATH.match(path or "")
    return bool(m) and m.group("job") == str(job_id)


def clean_name(name: str | None) -> str:
    """The file's own name, safe for a header and a link."""
    cleaned = re.sub(r"[/\\\r\n\t\"]", " ", name or "").strip()
    return " ".join(cleaned.split())[:120] or "receipt"


# ── What comes back ──────────────────────────────────────────────────────────

# Twelve or more digits in a row (spaces or dashes allowed) reads like a card
# or account number; cut it, whatever field it turned up in.
_LONG_NUMBER = re.compile(r"(?:\d[ -]?){12,}")


def _text(value) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    cleaned = " ".join(_LONG_NUMBER.sub("", value).split())
    if not cleaned or cleaned.lower() in ("null", "none", "n/a", "unknown"):
        return None
    return cleaned[:_MAX_FIELD]


def to_cents(value) -> int | None:
    """84.5, "84.50", "$1,234.56", "-12.00" → exact cents. Anything else → None."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").strip()
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    cents = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents if abs(cents) <= MAX_CENTS else None


def _date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        d = date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
    return d.isoformat() if 2000 <= d.year <= 2100 else None


def clean_lines(raw, batch_category: str | None = None) -> list[dict]:
    """The model's answer as draft PC log lines.

    `batch_category` is the producer's "these are all…" — when set, every line
    goes in that column whatever the model guessed (a lunch receipt could be
    per diem or a client meal; the paper can't say which, she can).

    A refund comes back negative, and a PC log line can't be: those are left
    for the producer, not guessed at. Raises ValueError if the answer isn't a
    list — a failed read, which she should hear as different from "nothing found".
    """
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("expected a JSON array of lines")
    out = []
    for item in raw[:MAX_LINES]:
        if not isinstance(item, dict):
            continue
        cents = to_cents(item.get("total"))
        if cents is None or cents <= 0:
            continue
        cat = batch_category if batch_category in CATEGORIES else (
            item.get("category") if item.get("category") in CATEGORIES else "production_misc")
        out.append({"spent_on": _date(item.get("date")), "payee": _text(item.get("payee")) or "",
                    "description": _text(item.get("description")) or "", "amount_cents": cents,
                    "category": cat})
    return out


def read_receipt(data: bytes, batch_category: str | None = None,
                 on_usage: claude_service.UsageCallback = None) -> tuple[bytes, str, list[dict]]:
    """Check, shrink, read, clean. Returns (the file to keep, its type, the
    draft lines). Blocking — the router runs it in a thread. A refused file
    never reaches the model, so `on_usage` is never called for one."""
    kept, media_type = prepare(data)
    raw = claude_service.parse_receipt(kept, media_type, LEGEND, on_usage)
    return kept, media_type, clean_lines(raw, batch_category)
