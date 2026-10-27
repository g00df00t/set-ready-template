"""Render a stored call sheet to a print-ready PDF for email attachment.

WeasyPrint rather than headless Chromium: the sheet is inline-styled tables
with no JavaScript, which is squarely what WeasyPrint handles well, and it
costs ~50MB in the image instead of ~400MB for Chromium on a backend that has
to stay responsive during a shoot.
"""

import logging
import re

logger = logging.getLogger(__name__)

# WeasyPrint narrates every render step at INFO — seven lines per send in the
# Railway logs. Warnings and errors still come through.
logging.getLogger("weasyprint").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)

# Emoji have no glyph in WeasyPrint's font stack and render as tofu boxes or
# stray colored artifacts. On paper they carry nothing anyway — the map links
# aren't clickable in print. Ranges chosen to leave en/em dashes (U+2013/2014)
# alone, since the sheet uses those in time ranges.
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoji, pictographs, transport, symbols
    "\U00002600-\U000027BF"   # misc symbols and dingbats
    "\U00002B00-\U00002BFF"   # misc symbols and arrows
    "\U0000FE0F"              # variation selector-16
    "]"
)

# The sheet is authored at 680px for email. On US Letter it gets the full text
# width instead. Same font stack as the browser print path, or elements with no
# explicit font-family fall back to serif and the PDF stops matching the app.
_PRINT_CSS = """
  @page { size: letter; margin: 0.35in; }
  html, body { font-family: system-ui, -apple-system, Arial, sans-serif; margin: 0; }
  body > div { max-width: 100% !important; width: 100% !important; }
  tr { break-inside: avoid; }
  thead { break-after: avoid; }
"""


def render_call_sheet_pdf(sheet_html: str) -> bytes:
    """Render sheet HTML to PDF bytes. Raises on failure — the caller decides
    whether a failed attachment should block the send."""
    # Imported lazily: if a system library is missing on a deploy, that should
    # break PDF attachment, not stop the whole API from starting.
    from weasyprint import HTML

    document = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<style>{_PRINT_CSS}</style></head><body>"
        f"{_EMOJI.sub('', sheet_html)}"
        "</body></html>"
    )
    return HTML(string=document).write_pdf()


def safe_pdf_filename(project_name: str) -> str:
    """A filename that survives every mail client. Crew save these to a phone,
    so it should read as the job, not as a UUID."""
    # Replace punctuation with a space rather than deleting it, or a name like
    # "Fall - TM/OGIO/Cotopaxi" collapses into "TMOGIOCotopaxi".
    cleaned = re.sub(r"[^\w\s-]", " ", project_name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return f"Call Sheet - {cleaned}.pdf" if cleaned else "Call Sheet.pdf"
