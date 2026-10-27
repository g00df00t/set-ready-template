"""Build a deal memo: prepare the data, then render it.

Same two-stage split as call_sheet_builder.py, and the same reason — the
router doesn't need to know the memo is assembled from a project row, a crew
row and a Roster row before it's rendered.
"""

from services.deal_memo_data import build_deal_memo_data
from services.deal_memo_template import render_deal_memo


def build_deal_memo(
    project: dict,
    crew_member: dict,
    roster_entry: dict | None,
    location: dict | None = None,
    dates: str | None = None,
) -> str:
    return render_deal_memo(build_deal_memo_data(project, crew_member, roster_entry, location, dates))
