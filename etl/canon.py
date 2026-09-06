"""Turn the publisher's value vocabulary into the one YIELDMAP models in.

Every function here is deliberately conservative: when a value cannot be understood it returns
``None`` rather than a guess. A null propagates into a smaller sample size and a lower confidence
badge, which is honest. A guess propagates into a number someone might act on.
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------- rooms

_ROOM_WORDS: dict[str, int] = {
    "studio": 0,
    "single room": 0,
    "1 b/r": 1,
    "2 b/r": 2,
    "3 b/r": 3,
    "4 b/r": 4,
    "5 b/r": 5,
    "6 b/r": 6,
    "7 b/r": 7,
    "8 b/r": 8,
    "9 b/r": 9,
    "10 b/r": 10,
}
_ROOM_NUMBER = re.compile(r"(\d{1,2})\s*(?:b\s*/?\s*r|bed|bedroom|br)\b", re.IGNORECASE)
# Values that name a property kind rather than a bedroom count. Mapping these to a number would
# invent a comparison that does not exist.
_NOT_A_ROOM_COUNT = {"penthouse", "office", "shop", "warehouse", "land", "hotel", "n/a", "na", ""}

MAX_ROOMS = 20


def canon_rooms(value: str | int | float | None) -> int | None:
    """Bedroom count from the publisher's room label, or None when it is not a bedroom count.

    "Studio" is zero bedrooms, not missing: a studio genuinely has none, and treating it as null
    would drop the whole studio segment out of every yield table.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        return n if 0 <= n <= MAX_ROOMS else None

    text = " ".join(str(value).strip().lower().split())
    if text in _NOT_A_ROOM_COUNT:
        return None
    if text in _ROOM_WORDS:
        return _ROOM_WORDS[text]
    if match := _ROOM_NUMBER.search(text):
        n = int(match.group(1))
        return n if 0 <= n <= MAX_ROOMS else None
    if text.isdigit():
        n = int(text)
        return n if 0 <= n <= MAX_ROOMS else None
    return None


def rooms_label(rooms: int | None) -> str:
    """Display label for a bedroom count, used as a grouping key across the app."""
    if rooms is None:
        return "unknown"
    if rooms == 0:
        return "studio"
    return f"{rooms}br"


# -------------------------------------------------------------------- property type

_PROPERTY_TYPES: dict[str, str] = {
    "unit": "unit",
    "flat": "unit",
    "apartment": "unit",
    "villa": "villa",
    "villa/house": "villa",
    "house": "villa",
    "land": "land",
    "plot": "land",
    "building": "building",
    "office": "office",
    "shop": "retail",
    "retail": "retail",
    "warehouse": "industrial",
}


def canon_property_type(value: str | None) -> str | None:
    """Collapse the publisher's type vocabulary onto the handful this project models."""
    if value is None:
        return None
    text = " ".join(str(value).strip().lower().split())
    return _PROPERTY_TYPES.get(text)


# ------------------------------------------------------------------------ off-plan

_OFFPLAN_MARKERS = ("off-plan", "off plan", "offplan", "pre-registration", "pre registration")
_EXISTING_MARKERS = ("existing", "ready", "resale", "secondary")


def canon_is_offplan(reg_type: str | None, procedure: str | None = None) -> bool | None:
    """Whether a transaction is off-plan.

    Two fields carry the signal and they can disagree, so both are read: the registration type is
    authoritative, and the procedure name is the fallback for rows where it is blank.
    """
    for field in (reg_type, procedure):
        if not field:
            continue
        text = str(field).strip().lower()
        if any(m in text for m in _OFFPLAN_MARKERS):
            return True
        if any(m in text for m in _EXISTING_MARKERS):
            return False
    return None


# --------------------------------------------------------------------------- area

# Apostrophes mark a glottal stop in transliterated Arabic and the publisher uses them
# inconsistently: "Za'abeel" and "Zaabeel" are the same place. They are deleted rather than turned
# into a space, or the two spellings would land on different keys.
_ELIDED = re.compile(r"[\u2019\u02bc\u02bb'`]")
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def canon_area_key(value: str | None) -> str | None:
    """A stable join key for an area name.

    The same community appears as "Al Barsha South Fourth", "AL BARSHA SOUTH FOURTH" and
    "Al Barsha South  Fourth" across files and years. The key strips accents, punctuation, case and
    repeated spaces so those all land on one area rather than three.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _ELIDED.sub("", text.lower())
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return text or None


def canon_area_name(value: str | None) -> str | None:
    """Display form of an area name: original spacing collapsed, original casing kept."""
    if value is None:
        return None
    text = _SPACES.sub(" ", str(value).strip())
    return text or None


# -------------------------------------------------------------------------- money

# Guards against the values that make a median meaningless. These are not outlier detection --
# that is a model in finance/anomalies.py -- they are impossibility checks.
MIN_PRICE_AED = 1_000.0
MAX_PRICE_AED = 5_000_000_000.0
MIN_AREA_SQM = 5.0
MAX_AREA_SQM = 1_000_000.0


def canon_price(value: float | int | str | None) -> float | None:
    """A price in AED, or None when the value cannot be a price."""
    number = _to_float(value)
    if number is None or not (MIN_PRICE_AED <= number <= MAX_PRICE_AED):
        return None
    return number


def canon_area_sqm(value: float | int | str | None) -> float | None:
    """A floor area in square metres, or None when the value cannot be one."""
    number = _to_float(value)
    if number is None or not (MIN_AREA_SQM <= number <= MAX_AREA_SQM):
        return None
    return number


def price_per_sqm(price_aed: float | None, area_sqm: float | None) -> float | None:
    """Derived price per square metre.

    Derived rather than read from the publisher's own column so that it is always consistent with
    the price and area this project actually stored.
    """
    if price_aed is None or area_sqm is None or area_sqm <= 0:
        return None
    return price_aed / area_sqm


def _to_float(value: float | int | str | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value and abs(value) != float("inf") else None
    text = str(value).strip().replace(",", "").replace("AED", "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None
