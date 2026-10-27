import logging
import httpx
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime, date
from urllib.parse import quote

# Address/coordinate traces are logged at DEBUG so they never reach prod stdout
# (default level is INFO) — a shoot location can be someone's home. Real failures
# are logged at WARNING.
logger = logging.getLogger(__name__)

WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


# Address -> coordinates, for the life of the process. Same reasoning as the
# hospital cache: a project's address rarely changes between regenerations, and
# Nominatim asks callers not to repeat identical queries. Keyed on the trimmed,
# lowercased address so casing and stray whitespace share an entry.
_geocode_cache: dict[str, tuple[float, float] | None] = {}
_GEOCODE_CACHE_MAX = 512


def geocode(address: str) -> tuple[float, float] | None:
    key = (address or "").strip().lower()
    if key in _geocode_cache:
        logger.debug("[location] Geocode cache hit")
        return _geocode_cache[key]

    logger.debug(f"[location] Geocoding: {address!r}")
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "SetReady/1.0 (call-sheet-generator)"},
            timeout=8,
        )
        data = r.json()
        if data:
            lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
            logger.debug(f"[location] Geocoded to ({lat}, {lon})")
            if len(_geocode_cache) < _GEOCODE_CACHE_MAX:
                _geocode_cache[key] = (lat, lon)
            return lat, lon
        logger.debug("[location] Geocode returned no results")
    except Exception as e:
        logger.warning(f"[location] Geocode error: {e}")
    return None


def _fmt_time(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        hour = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{hour}:{dt.minute:02d} {ampm}"
    except Exception:
        return None


def get_weather(lat: float, lon: float, shoot_date: str) -> dict | None:
    logger.debug(f"[location] Fetching weather for {shoot_date} at ({lat}, {lon})")
    today = date.today()
    try:
        shoot = date.fromisoformat(shoot_date)
    except ValueError:
        logger.debug(f"[location] Invalid shoot_date format: {shoot_date}")
        return None

    days_delta = (shoot - today).days

    # Forecast API covers roughly -92 to +16 days; archive covers past dates
    # Beyond 16 days in the future, no forecast data exists — skip gracefully
    if days_delta > 16:
        logger.debug(f"[location] Shoot date {shoot_date} is {days_delta} days away — too far for forecast, skipping weather")
        return None
    elif days_delta >= -92:
        url = "https://api.open-meteo.com/v1/forecast"
        daily_params = "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode,sunrise,sunset"
    else:
        url = "https://archive-api.open-meteo.com/v1/archive"
        daily_params = "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,sunrise,sunset"

    try:
        r = httpx.get(
            url,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": daily_params,
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "start_date": shoot_date,
                "end_date": shoot_date,
            },
            timeout=10,
        )
        data = r.json()
        logger.debug(f"[location] Weather API response keys: {list(data.keys())}")

        if "error" in data:
            logger.warning(f"[location] Weather API error: {data.get('reason', data['error'])}")
            return None

        daily = data.get("daily", {})
        if not daily or not daily.get("weathercode"):
            logger.debug("[location] Weather: no daily data in response")
            return None

        code = daily["weathercode"][0]
        high = daily.get("temperature_2m_max", [None])[0]
        low = daily.get("temperature_2m_min", [None])[0]
        sunrise_raw = daily.get("sunrise", [None])[0]
        sunset_raw = daily.get("sunset", [None])[0]

        # precipitation_probability for forecast, precipitation_sum for archive
        precip_chance = daily.get("precipitation_probability_max", [None])[0]
        if precip_chance is None:
            precip_sum = daily.get("precipitation_sum", [None])[0]
            precip_chance = 100 if (precip_sum and precip_sum > 0) else 0

        result = {
            "condition": WMO_CODES.get(code, "Variable"),
            "high_f": round(high) if high is not None else None,
            "low_f": round(low) if low is not None else None,
            "precipitation_chance": int(precip_chance) if precip_chance is not None else None,
            "sunrise": _fmt_time(sunrise_raw),
            "sunset": _fmt_time(sunset_raw),
        }
        logger.debug(f"[location] Weather result: {result}")
        return result
    except Exception as e:
        logger.warning(f"[location] Weather error: {e}")
    return None


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def miles_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line miles between two geocoded points.

    Deliberately not drive time — that needs a routing provider we don't have.
    For "how far is my hotel from set" a crow-flies figure is honest and useful,
    as long as the sheet labels it as distance rather than implying a duration.
    """
    return round(_haversine_miles(a[0], a[1], b[0], b[1]), 1)


# Radius ladder for the hospital lookup, in metres.
#
# Overpass cost scales with the area searched, and 25km around a city centre is
# a lot of area: measured at 7.2s against 2.5s for 5km, both returning the same
# correct answer. Nearly every shoot has a hospital within 5km, so ask small
# first and only widen when the small answer is genuinely empty — which is the
# rural case, where the wider search is worth its cost because there is no
# closer answer to find.
_HOSPITAL_RADII_M = (5_000, 15_000, 40_000)

# Per-endpoint HTTP timeout, down from 20s.
#
# Not lower than this, even though the working endpoint usually answers a dense
# city in 1–4s. Overpass is a free shared service and slows under load; at 7s a
# busy moment produced no hospital at all for Los Angeles, and an absent safety
# line is worse than a slow one. 10s keeps the worst case well under the old
# 20s-per-endpoint behaviour while leaving room for a bad minute.
#
# Overpass's own [timeout:] is set just under it so the server gives up before
# the client does and we get a real error rather than a dropped connection.
_OVERPASS_TIMEOUT_S = 10

# Order matters: the first endpoint that answers wins, so a dead one at the
# front costs its full timeout on every single lookup.
#
# kumi.systems was first and timed out on every request measured — 7.4s each
# time, twice in a row, while overpass-api.de answered the same query in
# 1.3–4.3s. That one ordering was most of the hospital lookup's latency. It
# stays as a fallback in case the main instance rate-limits, which it does under
# load; it just no longer gets first refusal.
_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

# Coordinates -> result, for the life of the process.
#
# Generating a call sheet is not a one-shot action: producers regenerate after
# every change to crew, schedule or times, and the location almost never moves
# between those runs. Without this, each regeneration pays the full Overpass
# round trip again for an answer that cannot have changed.
#
# Rounded to ~11m so trivially different geocodes of the same address share an
# entry. Bounded so a long-running process can't grow without limit, and holds
# only public facility data — no customer content.
_hospital_cache: dict[tuple[float, float], dict | None] = {}
_HOSPITAL_CACHE_MAX = 512


def _overpass_hospitals(lat: float, lon: float, radius_m: int) -> list | None:
    """Raw Overpass hits within `radius_m`. None means the request failed, which
    is different from an empty list meaning nothing is there."""
    query = f"""
[out:json][timeout:{_OVERPASS_TIMEOUT_S - 1}];
(
  node["amenity"="hospital"](around:{radius_m},{lat},{lon});
  way["amenity"="hospital"](around:{radius_m},{lat},{lon});
  relation["amenity"="hospital"](around:{radius_m},{lat},{lon});
);
out center;
"""
    for endpoint in _OVERPASS_ENDPOINTS:
        try:
            r = httpx.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": "SetReady/1.0"},
                timeout=_OVERPASS_TIMEOUT_S,
            )
            if r.status_code == 200 and r.text.strip().startswith("{"):
                return r.json().get("elements", [])
            logger.debug(f"[location] Overpass {endpoint} HTTP {r.status_code}")
        except Exception as e:
            logger.warning(f"[location] Overpass {endpoint} error: {e}")
    return None


def get_nearest_hospital(lat: float, lon: float) -> dict | None:
    """Nearest hospital to the shoot, for the call sheet's safety line.

    The query is UNLIMITED within whatever radius it searches. It used to end
    `out center 10`, which caps the result set at ten arbitrary matches —
    Overpass does not order by distance — and the nearest-of-ten was then picked
    here. In a dense city that silently returns the wrong answer: near Griffith
    Park it named a downtown clinic 7.6 miles away when the closest was 2.5.
    Crew read this line when someone is hurt, so the sort has to see every
    candidate inside the radius.
    """
    key = (round(lat, 4), round(lon, 4))
    if key in _hospital_cache:
        logger.debug(f"[location] Hospital cache hit for {key}")
        return _hospital_cache[key]

    logger.debug(f"[location] Querying nearest hospital near ({lat}, {lon})")
    try:
        elements: list = []
        for radius in _HOSPITAL_RADII_M:
            found = _overpass_hospitals(lat, lon, radius)
            if found is None:
                # Every endpoint failed. Don't cache a transport failure as
                # "no hospital nearby" — the next generation should retry.
                logger.warning("[location] All Overpass endpoints failed")
                return None
            if found:
                elements = found
                logger.debug(f"[location] {len(found)} hospitals within {radius}m")
                break

        if not elements:
            if len(_hospital_cache) < _HOSPITAL_CACHE_MAX:
                _hospital_cache[key] = None
            return None

        best = None
        best_dist = float("inf")
        for el in elements:
            hlat = el.get("lat") or (el.get("center") or {}).get("lat")
            hlon = el.get("lon") or (el.get("center") or {}).get("lon")
            if hlat is None or hlon is None:
                continue
            dist = _haversine_miles(lat, lon, float(hlat), float(hlon))
            if dist < best_dist:
                best_dist = dist
                best = el

        if not best:
            return None

        tags = best.get("tags", {})
        name = tags.get("name", "Hospital")
        best_lat = best.get("lat") or (best.get("center") or {}).get("lat")
        best_lon = best.get("lon") or (best.get("center") or {}).get("lon")

        addr_parts = []
        num = tags.get("addr:housenumber", "")
        street = tags.get("addr:street", "")
        if num and street:
            addr_parts.append(f"{num} {street}")
        elif street:
            addr_parts.append(street)
        if tags.get("addr:city"):
            addr_parts.append(tags["addr:city"])
        if tags.get("addr:state"):
            addr_parts.append(tags["addr:state"])

        # Map links are built here, from the hospital's own coordinates, rather
        # than from its address the way the shoot location's links are. OSM
        # frequently has no addr:* tags on a hospital, so an address-based link
        # would be missing exactly when someone needs it most. Coordinates always
        # exist (they're how we picked this one) and drop the pin on the building
        # instead of on a same-named branch across town.
        coord = f"{best_lat},{best_lon}" if best_lat is not None and best_lon is not None else None
        result = {
            "name": name,
            "address": ", ".join(addr_parts) if addr_parts else None,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "distance_miles": round(best_dist, 1),
            "apple_maps_url": f"https://maps.apple.com/?ll={coord}&q={quote(name)}" if coord else None,
            "google_maps_url": f"https://www.google.com/maps/search/?api=1&query={coord}" if coord else None,
        }
        logger.debug(f"[location] Nearest hospital: {result}")
        if len(_hospital_cache) < _HOSPITAL_CACHE_MAX:
            _hospital_cache[key] = result
        return result
    except Exception as e:
        logger.warning(f"[location] Hospital error: {e}")
    return None
