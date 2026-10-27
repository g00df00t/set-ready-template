"""The per diem sheet as files: Excel (what the producer keeps today, and the receipt at
reconciliation) and a PDF to print and have crew sign. Both read one sheet
from services/per_diem.build_sheet and nothing else.

Layout follows her sheet (docs/producer-documents-map.md §1.6): the job name as
title, the group, then a date row, a weekday row and a day row ("Shoot Brand
A") over the day columns; Crew Name · Notes · one column per day · Total ·
Paid ("Initials"); and a Totals row. Amounts are numbers with live SUMs, so
she can still change a cell in Excel and have the totals follow.
"""

import io
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.job_dates import LABELS
from services.job_rates import money

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONEY_FORMAT = '"$"#,##0.##'


def _head(col: dict) -> tuple[str, str, str]:
    d = date.fromisoformat(col["date"])
    what = " / ".join(LABELS[t] for t in col["types"])
    if col.get("label"):
        what = f"{what} {col['label']}".strip()
    return f"{d.month}/{d.day}", _WEEKDAYS[d.weekday()], what


def title(job: dict) -> str:
    return f"Per Diem - {job.get('name') or 'Job'}"


def to_xlsx(job: dict, sheet: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Per diem"
    bold = Font(bold=True)
    ws.append([title(job)])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Group:", job.get("client_name") or ""])
    ws.cell(row=2, column=1).font = bold
    rates = sheet["rates"]
    ws.append(["Rate:", f"{rates['other'] or '—'} non-shoot day · {rates['shoot'] or '—'} shoot day"])
    ws.cell(row=3, column=1).font = bold
    ws.append([])

    cols = sheet["dates"]
    first = 3                                   # Crew Name, Notes, then days
    heads = [_head(c) for c in cols]
    ws.append(["", "Dates"] + [h[0] for h in heads] + ["", ""])
    ws.append(["", "Days"] + [h[1] for h in heads] + ["", ""])
    ws.append(["Crew Name", "Notes"] + [h[2] for h in heads] + ["Total", "Paid"])
    for r in range(ws.max_row - 2, ws.max_row + 1):
        for c in range(1, first + len(cols) + 2):
            ws.cell(row=r, column=c).font = bold
            ws.cell(row=r, column=c).alignment = Alignment(horizontal="center" if c >= first else "left", wrap_text=True)

    top = ws.max_row + 1
    for row in sheet["rows"]:
        ws.append([row["name"], row["notes"]] + [row["cells"].get(c["date"]) for c in cols] + [None, row["paid_text"]])
        n = ws.max_row
        a = ws.cell(row=n, column=first).coordinate
        b = ws.cell(row=n, column=first + len(cols) - 1).coordinate
        ws.cell(row=n, column=first + len(cols), value=f"=SUM({a}:{b})")
        for c in range(first, first + len(cols) + 1):
            ws.cell(row=n, column=c).number_format = MONEY_FORMAT
    bottom = ws.max_row

    ws.append(["Totals", ""] + [None for _ in cols] + [None, ""])
    n = ws.max_row
    for i in range(len(cols) + 1):
        col = ws.cell(row=n, column=first + i).column_letter
        ws.cell(row=n, column=first + i, value=f"=SUM({col}{top}:{col}{bottom})" if bottom >= top else 0)
        ws.cell(row=n, column=first + i).number_format = MONEY_FORMAT
        ws.cell(row=n, column=first + i).font = bold
    ws.cell(row=n, column=1).font = bold

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 28
    for i in range(len(cols) + 2):
        ws.column_dimensions[ws.cell(row=1, column=first + i).column_letter].width = 13
    ws.column_dimensions[ws.cell(row=1, column=first + len(cols) + 1).column_letter].width = 22
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_env: Environment | None = None


def _environment() -> Environment:
    global _env
    if _env is None:
        _env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                           autoescape=select_autoescape(["html", "j2", "html.j2"], default=True),
                           trim_blocks=True, lstrip_blocks=True)
    return _env


def to_html(job: dict, sheet: dict) -> str:
    cols = [{"key": c["date"], "date": h[0], "weekday": h[1], "what": h[2]}
            for c, h in ((c, _head(c)) for c in sheet["dates"])]
    rows = [{**r, "cells": {d: money(v) for d, v in r["cells"].items()}, "total": money(r["total"])}
            for r in sheet["rows"]]
    return _environment().get_template("per_diem_sheet.html.j2").render(
        title=title(job), group=job.get("client_name") or "", rates=sheet["rates"], cols=cols, rows=rows,
        totals={d: money(v) if v else "" for d, v in sheet["totals"].items()}, total=money(sheet["total"]))
