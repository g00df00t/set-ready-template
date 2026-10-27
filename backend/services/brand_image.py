"""Prepare a company's title-card artwork.

A different job from the call-sheet attachments, which are documents a producer
sends. This is a backdrop: it sits behind a wordmark, at a wide aspect, and it
only ever appears on a screen. So it is re-encoded rather than merely shrunk —
to a fixed maximum width, always as JPEG, always flattened.

Flattening is the part that matters. Transparency cannot survive a JPEG, and a
title card is a plate with the artwork covering it edge to edge; a PNG with an
alpha channel composited onto black would lose whatever the transparent regions
were meant to reveal. Compositing onto the card's own near-black ground is not
a guess here — it is the exact colour the image will sit on.
"""

import io
import logging

logger = logging.getLogger(__name__)

#: Wider than any title card is drawn, and small enough that a crew member on
#: mobile data isn't waiting on a 4000px painting before they can read their
#: call time.
MAX_WIDTH = 1600

#: The title card's own plate colour. Transparent regions become this, so a
#: flattened image sits seamlessly on the card rather than on a black rectangle.
PLATE = (16, 24, 32)

_QUALITY = 82


class UnreadableImage(Exception):
    """The bytes weren't an image we can open."""


def prepare(data: bytes) -> tuple[bytes, int, int]:
    """Artwork in, (jpeg bytes, width, height) out.

    Raises UnreadableImage for anything Pillow can't open — unlike the
    attachment path, which keeps the original when it can't improve it. A file
    we can't decode here would become a broken backdrop on every crew member's
    confirm page, so refusing it up front is the kinder failure.
    """
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise UnreadableImage(str(e)) from e

    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        plate = Image.new("RGB", img.size, PLATE)
        plate.paste(img, mask=img.split()[-1])
        img = plate
    else:
        img = img.convert("RGB")

    if img.width > MAX_WIDTH:
        height = round(img.height * MAX_WIDTH / img.width)
        img = img.resize((MAX_WIDTH, height), Image.LANCZOS)

    out = io.BytesIO()
    # progressive: the card is the first thing on the page, so a painting that
    # resolves in passes reads better than one that wipes down in a band.
    img.save(out, format="JPEG", quality=_QUALITY, optimize=True, progressive=True)
    return out.getvalue(), img.width, img.height
