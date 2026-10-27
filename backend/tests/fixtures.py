"""Call sheet inputs, built to exercise the paths that break.

Every section of the sheet is conditional, so every section has a null path.
These are deliberately synthetic: real projects cover whatever they happen to
cover, and the 18 stored call sheets belong to four accounts and hold real crew
names, phone numbers and shoot locations. Fixtures cover what we choose.

Each fixture is the `project_data` dict services/call_sheet_data.py assembles —
the contract the renderer consumes. Times are raw Postgres values here, exactly
as they arrive, because formatting them is the renderer's job.
"""


def _base() -> dict:
    """A full sheet with every section populated. Others narrow this."""
    return {
        "project": {"name": "Northwind Athletic — Spring Campaign", "shoot_date": "2026-09-14"},
        "header_times": [
            {"label": "FIRST CALL", "time": "6:30 AM"},
            {"label": "FIRST SHOT", "time": "8:30 AM"},
            {"label": "LUNCH", "time": "12:30 PM"},
            {"label": "EST. WRAP", "time": "6:30 PM"},
        ],
        "crew": [
            {"name": "Dana Whitfield", "role": "Producer", "department": "Production",
             "call_time": "06:30:00", "email": "dana@example.com", "phone": "310-555-0100"},
            {"name": "Marcus Feld", "role": "1st AD", "department": "Production",
             "call_time": "06:30:00", "email": "marcus@example.com", "phone": "310-555-0101"},
            {"name": "Tomas Vance", "role": "Director of Photography", "department": "Camera",
             "call_time": "07:00:00", "email": "tomas@example.com", "phone": "310-555-0102"},
            {"name": "Aisha Bello", "role": "Gaffer", "department": "Grip & Electric",
             "call_time": "06:30:00", "email": "aisha@example.com", "phone": "310-555-0103"},
        ],
        "schedule": [
            {"start_time": "06:30:00", "end_time": "07:00:00", "description": "Crew call — G&E offload"},
            {"start_time": "08:30:00", "end_time": "11:00:00", "description": "SCENE 1 — Sunrise run"},
            {"start_time": "12:30:00", "end_time": "13:15:00", "description": "LUNCH"},
            {"start_time": "17:30:00", "end_time": None, "description": "Wrap and load out"},
        ],
        "location": {
            "location_name": "Griffith Park — Crystal Springs Meadow",
            "address": "4730 Crystal Springs Dr, Los Angeles, CA 90027",
            "parking_address": "4801 Crystal Springs Dr, Los Angeles, CA 90027",
            "parking_notes": "Crew park in Lot B. Shuttle every 15 min from 6:15 AM.",
            "additional_notes": "Park rangers on site; no open flame.",
        },
        "company_moves": [],
        "agency_and_client_contacts": [
            {"organization": "Meridian & Co.", "name": "Harriet Vaughn",
             "role": "Agency Producer", "call_time": "09:00:00"},
            {"organization": "Northwind Athletic", "name": "Grace Delacroix",
             "role": "Brand Marketing Lead", "call_time": "10:00:00"},
        ],
        "talent": [
            {"name": "Imani Cole", "role": "Lead Athlete", "call_time": "08:00:00",
             "email": "imani@example.com", "phone": "310-555-0210",
             "location_label": "Griffith Park — Crystal Springs Meadow"},
            {"name": "Diego Salas", "role": "Second Athlete", "call_time": "09:00:00",
             "email": "diego@example.com", "phone": "310-555-0211",
             "location_label": "Griffith Park — Crystal Springs Meadow"},
        ],
        "weather": {"condition": "Clear sky", "high_f": 94, "low_f": 78,
                    "precipitation_chance": 4, "sunrise": "6:35 AM", "sunset": "7:01 PM"},
        "nearest_hospital": {
            "name": "Providence Saint Joseph Medical Center",
            "address": "501 South Buena Vista Street, Burbank",
            "phone": "818-843-5111", "distance_miles": 2.1,
            "apple_maps_url": "https://maps.apple.com/?ll=34.15,-118.32&q=Providence",
            "google_maps_url": "https://www.google.com/maps/search/?api=1&query=34.15,-118.32",
        },
        "meal_plan": [
            {"label": "BREAKFAST", "start": "6:30 AM", "end": "7:00 AM", "notes": None},
            {"label": "LUNCH", "start": "12:30 PM", "end": "1:15 PM",
             "notes": "Catering at basecamp.\nVegetarian option available."},
        ],
        "accommodation": {
            "hotel_name": "Courtyard by Marriott Los Angeles Burbank Airport",
            "address": "2100 Empire Ave, Burbank, CA 91504",
            "phone": "818-843-5333", "website_url": "https://example.com/hotel",
            "room_block": "NORTHWIND", "check_in_time": "15:00:00",
            "check_out_time": "11:00:00",
            "amenities": "Breakfast included.\nParking $12/night.",
            "notes": "Ask for the production rate.",
            "distance_from_set_miles": 8.4,
        },
    }


def full() -> dict:
    """Everything present. The densest sheet."""
    return _base()


def minimal() -> dict:
    """Crew and nothing else — the sparse sheet, where nulls bite.

    No location means no map links, no hospital, no weather. This is a real
    shape: a producer who has added crew and not yet filled anything in.
    """
    d = _base()
    d.update({
        "header_times": [], "schedule": [], "location": None, "company_moves": [],
        "agency_and_client_contacts": [], "talent": [], "weather": None,
        "nearest_hospital": None, "meal_plan": [], "accommodation": None,
    })
    return d


def no_weather() -> dict:
    """Shoot date beyond the forecast window. Observed for real on a date 21
    days out — the section simply isn't there."""
    d = _base()
    d["weather"] = None
    return d


def no_hospital() -> dict:
    """Remote location, Overpass finds nothing. Also real."""
    d = _base()
    d["nearest_hospital"] = None
    return d


def undepartmented_crew() -> dict:
    """No crew member has a department, so the table is flat with no sub-headers.

    Talent is cleared too. Both tables use the same grouping macro, so leaving
    grouped talent in would make "are there sub-headers on this page" true for
    the wrong reason — the first version of this fixture did exactly that and
    the test passed against talent's location groups.
    """
    d = _base()
    for m in d["crew"]:
        m["department"] = None
    d["talent"] = []
    return d


def mixed_departments() -> dict:
    """Some crew have a department and some don't. The undepartmented go last."""
    d = _base()
    d["crew"] = d["crew"] + [
        {"name": "Sam Okonkwo", "role": "Runner", "department": None,
         "call_time": "07:00:00", "email": "sam@example.com", "phone": "310-555-0104"},
    ]
    return d


def redacted_and_noted() -> dict:
    """Two things that arrive looking like ordinary values but are not.

    `hide_contact` has already stripped phone and email upstream, so the
    renderer sees empty strings and must not print a blank-looking row. And a
    call_time_note ("Own Call") has been collapsed into `call_time`, so that
    field holds a string that is not a time — it must pass through verbatim
    rather than being formatted or dropped.
    """
    d = _base()
    d["crew"] = [
        {"name": "Priya Anand", "role": "2nd AD", "department": "Production",
         "call_time": "Own Call", "email": "", "phone": ""},
        {"name": "Robin Mercer", "role": "1st AC", "department": "Camera",
         "call_time": None, "email": "robin@example.com", "phone": "310-555-0105"},
    ]
    return d


def no_contact_columns() -> dict:
    """Nobody has a phone or an email, so both columns are omitted entirely.

    Talent cleared for the same reason as `undepartmented_crew` — talent has its
    own phone and email columns, and their presence would mask a crew-table
    regression.
    """
    d = _base()
    for m in d["crew"]:
        m["phone"] = None
        m["email"] = None
    d["talent"] = []
    return d


def company_moves() -> dict:
    """Two moves, one with its own nearest hospital."""
    d = _base()
    d["company_moves"] = [
        {"location_name": "Ridge Trail", "address": "2800 E Observatory Rd, Los Angeles, CA 90027",
         "move_time": "11:00:00", "parking_notes": "Roadside pullout, 6 vehicles max.",
         "parking_address": None, "additional_notes": None, "nearest_hospital": None},
        {"location_name": "Basecamp Two", "address": "4400 Crystal Springs Dr, Los Angeles, CA 90027",
         "move_time": "15:30:00", "parking_notes": None, "parking_address": None,
         "additional_notes": "Generators off after 6 PM.",
         "nearest_hospital": {"name": "Children's Hospital Los Angeles",
                              "address": "4650 Sunset Blvd, Los Angeles",
                              "phone": "323-660-2450", "distance_miles": 3.0,
                              "apple_maps_url": None, "google_maps_url": None}},
    ]
    return d


def long_emails() -> dict:
    """Realistic email addresses, which are much longer than name@example.com.

    Seeded staging data using plus-addressing (pat+nora@example.com)
    pushed the phone column narrow enough that numbers wrapped mid-digit. The
    short fixture addresses had hidden it entirely.
    """
    d = _base()
    for i, m in enumerate(d["crew"]):
        m["email"] = f"pat+{m['name'].split()[0].lower()}@example.com"
    return d


def long_names() -> dict:
    """The wrapping case the prompt spends a paragraph on. A long hospital name
    must wrap in its own cell rather than colliding with the phone number, and
    the same for a long hotel name against its distance."""
    d = _base()
    d["nearest_hospital"]["name"] = (
        "Ronald Reagan UCLA Medical Center — Department of Emergency Medicine, Westwood"
    )
    d["accommodation"]["hotel_name"] = (
        "Courtyard by Marriott New York Manhattan / Chelsea — Midtown West Annexe"
    )
    return d


def no_header_pills() -> dict:
    """No times set on the project at all, so the pills row is omitted."""
    d = _base()
    d["header_times"] = []
    return d


def hostile_text() -> dict:
    """Free text that must be escaped, not executed.

    Crew names, notes and locations are typed by a producer and rendered into
    HTML that crew members open. The old path let a model write the markup and
    cleaned up afterwards with nh3; a template escapes at the insertion point.
    """
    d = _base()
    d["crew"][0]["name"] = '<script>alert("xss")</script>'
    d["crew"][1]["role"] = 'Producer" onmouseover="alert(1)'
    d["location"]["parking_notes"] = "Lot B & C <b>only</b>"
    d["project"]["name"] = "Fish & Chips <Productions>"
    return d


ALL = {
    "full": full,
    "minimal": minimal,
    "no_weather": no_weather,
    "no_hospital": no_hospital,
    "undepartmented_crew": undepartmented_crew,
    "mixed_departments": mixed_departments,
    "redacted_and_noted": redacted_and_noted,
    "no_contact_columns": no_contact_columns,
    "company_moves": company_moves,
    "long_emails": long_emails,
    "long_names": long_names,
    "no_header_pills": no_header_pills,
    "hostile_text": hostile_text,
}
