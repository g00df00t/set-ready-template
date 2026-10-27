"""Shrink producer-supplied call sheet attachments to something that will send.

The motivating file was a two-slide Keynote export — an annotated map and a
scout photo board — at 23.6MB. SendGrid caps a message near 30MB and base64
inflates by a third, so that file exceeds the limit on its own, before the call
sheet PDF and the HTML body. Accepting uploads as-is would mean a producer's
first attempt bounces and they're left to work out how to shrink a PDF, which
is exactly the kind of platform knowledge this tool exists to absorb.

The compression is deliberately selective. Nearly all the bulk in a file like
that is full-resolution camera photos; the map page is where small street labels
actually have to stay legible. So images are only touched once they're big
enough to be worth touching.
"""

import io
import logging

logger = logging.getLogger(__name__)

# Only images above this effective DPI get touched, which is what makes the
# compression selective rather than blunt. A phone photo dropped into a Keynote
# slide sits at many hundreds of DPI; a map screenshot sized to fill the slide
# sits near screen resolution. So the photos get resampled and the map — the
# page where small street labels have to stay readable — is left alone.
#
# Measured on the file this was built for: 23.6MB to 2.5MB in about 1.4s, with
# the SHOOT ZONE markers and street names visually unchanged.
_DPI_THRESHOLD = 200
_DPI_TARGET = 150

# A photo wider than this is being downsampled by every mail client anyway.
_MAX_DIMENSION = 1800

_JPEG_QUALITY = 75


def human_size(num_bytes: int) -> str:
    """'23.6 MB'. Used in producer-facing copy, so it should read like a file
    manager rather than a byte count."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _shrink_image_bytes(data: bytes) -> bytes | None:
    """Re-encode one image smaller. None when it isn't worth replacing."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        # Transparency can't survive a JPEG. Rather than compositing onto a
        # guessed background — which turns a transparent logo into a black box —
        # leave these alone. They're overlays and small either way.
        if img.mode in ("RGBA", "LA", "P"):
            return None
        img = img.convert("RGB")
        if max(img.size) > _MAX_DIMENSION:
            img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        shrunk = out.getvalue()
    except Exception:
        # A single unreadable image must not fail the whole upload — the file is
        # still perfectly sendable, just larger.
        logger.warning("Could not recompress an embedded image", exc_info=True)
        return None
    return shrunk if len(shrunk) < len(data) else None


def _compress_pdf(data: bytes) -> bytes:
    try:
        import pymupdf
    except ImportError:  # older releases only ship the `fitz` name
        import fitz as pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        doc.rewrite_images(
            dpi_threshold=_DPI_THRESHOLD,
            dpi_target=_DPI_TARGET,
            quality=_JPEG_QUALITY,
        )
        out = io.BytesIO()
        # garbage=4 drops the originals the rewrite orphaned; without it the
        # file gets *bigger*, since both copies stay in the document.
        doc.save(out, garbage=4, deflate=True, clean=True)
        return out.getvalue()
    finally:
        doc.close()


def compress(data: bytes, content_type: str) -> bytes:
    """Return smaller bytes, or the original when nothing could be improved.

    Never raises for content reasons: a file we can't shrink is still a file the
    producer can send, and failing the upload over it would be worse than
    sending something large.
    """
    try:
        if content_type == "application/pdf":
            result = _compress_pdf(data)
        elif content_type.startswith("image/"):
            result = _shrink_image_bytes(data) or data
        else:
            return data
    except Exception:
        logger.warning("Attachment compression failed; keeping the original", exc_info=True)
        return data
    # Compression can lose — a PDF of vector text has no photos to shrink, and
    # rewriting it just adds overhead. Keep whichever is smaller.
    return result if len(result) < len(data) else data
