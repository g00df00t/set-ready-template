"""Build a call sheet: prepare the data, then render it.

The router's single entry point, so nothing upstream needs to know the sheet is
made in two stages. Takes the same arguments the old generate_call_sheet() took
and returns the same thing — one HTML document.
"""

from services.call_sheet_data import build_project_data
from services.call_sheet_template import render_call_sheet


def build_call_sheet(
    project: dict,
    crew: list,
    schedule: list,
    location: dict | None,
    contacts: list | None = None,
    talent: list | None = None,
    weather: dict | None = None,
    hospital: dict | None = None,
    company_moves: list | None = None,
    accommodation: dict | None = None,
    meals: dict | None = None,
) -> str:
    return render_call_sheet(
        build_project_data(
            project, crew, schedule, location, contacts, talent,
            weather, hospital, company_moves, accommodation, meals,
        )
    )
