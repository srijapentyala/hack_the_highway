"""Turn a free-text event into incidents bound to ontology ids. No tool calls here."""
from __future__ import annotations

import re
from datetime import date, timedelta

from .world import TODAY, World

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
WD = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
MON = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
DATE_RX = re.compile(
    rf"\b(\d{{4}}-\d{{2}}-\d{{2}})\b"
    rf"|\b(next|last)\s+({WD})\b"
    rf"|\b({WD})\s+({MON})\s+(\d{{1,2}})\b"
    rf"|\b({MON})\s+(\d{{1,2}})\b",
    re.IGNORECASE,
)

OUTAGE_CUES = (
    "outage", "power failure", "we're dark", "we are dark",
    "lost production", "production is stopped", "production stopped",
)
DELAY_CUES = (
    "delayed", "can't make it", "cannot make it", "new eta", "original drop",
    "will now arrive", "waiting on", "was due",
)
QUALITY_CUES = (
    "quality alert", "quality bulletin", "faulty", "suspect", "contamination",
    "place the lot", "on hold",
)
UNCONFIRMED_CUES = (
    "rumor", "not confirmed", "nothing confirmed", "no dates", "no details",
    "may be off", "possible shortage", "someone on the floor", "sometime soon",
)
NOISE_CUES = ("brochure", "price list", "price-list", "where to find the new brochure")


def _norm(text: str) -> str:
    return (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def _shift_weekday(which: str, name: str) -> date:
    target = WEEKDAYS[name.lower()]
    if which == "next":
        ahead = (target - TODAY.weekday()) % 7
        if ahead == 0:
            ahead = 7
        return TODAY + timedelta(days=ahead)
    back = (TODAY.weekday() - target) % 7
    if back == 0:
        back = 7
    return TODAY - timedelta(days=back)


def _dated(year: int, month: int, day: int, weekday_name: str | None) -> date | None:
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if weekday_name and d.weekday() != WEEKDAYS[weekday_name.lower()]:
        return None
    return d


def find_dates(text: str) -> list[dict]:
    """Dates in reading order. Relative phrases use Monday 2027-03-08 as today."""
    found = []
    for m in DATE_RX.finditer(text):
        iso_m, which, rel_wd, wd, mon, day, mon2, day2 = m.groups()
        if iso_m:
            d = date.fromisoformat(iso_m)
        elif which:
            d = _shift_weekday(which.lower(), rel_wd)
            # "next Friday" after an already-later anchor is the Friday after that anchor,
            # not the coming Friday. "Can't make it next Monday, now next Friday" is the
            # Friday that follows that Monday.
            if which.lower() == "next" and found and d <= date.fromisoformat(found[-1]["date"]):
                while d <= date.fromisoformat(found[-1]["date"]):
                    d += timedelta(days=7)
        elif wd:
            d = _dated(2027, MONTHS[mon.lower()], int(day), wd)
        else:
            d = _dated(2027, MONTHS[mon2.lower()], int(day2), None)
        if d is None:
            continue
        found.append({"phrase": m.group(0), "date": d.isoformat(), "at": m.start()})
    return found


def _has(text: str, cues: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(c in low for c in cues)


def _unique(pairs: list[tuple[str, str, str]], typ: str) -> list[str]:
    ids = []
    for t, eid, _phrase in pairs:
        if t == typ and eid not in ids:
            ids.append(eid)
    return ids


def _ids(pattern: str, text: str) -> list[str]:
    out = []
    for m in re.findall(pattern, text, flags=re.IGNORECASE):
        val = m.upper()
        if val not in out:
            out.append(val)
    return out


def parse_event(world: World, event: dict) -> dict:
    """Rule reader. Returns disposition + incidents fully bound to company ids."""
    text = _norm(event["text"])
    segments = [s.strip() for s in re.split(r"\(\d+\)", text) if s.strip()]
    incidents = []
    saw_unconfirmed = False
    saw_noise = False
    incomplete = []

    for segment in segments:
        built, flags = _parse_segment(world, segment)
        saw_unconfirmed = saw_unconfirmed or flags["unconfirmed"]
        saw_noise = saw_noise or flags["noise"]
        if built:
            incidents.extend(built)
        elif flags["attempted"]:
            incomplete.append(segment[:180])

    if incidents:
        disposition = "act"
    elif saw_unconfirmed or incomplete:
        # A report that is not specific or confirmed is escalated. Never guessed.
        disposition = "unconfirmed"
    else:
        disposition = "noise"

    return {
        "disposition": disposition,
        "incidents": incidents,
        "incomplete": incomplete,
        "reader": "ontology",
    }


def _parse_segment(world: World, segment: str) -> tuple[list[dict], dict]:
    flags = {
        "unconfirmed": _has(segment, UNCONFIRMED_CUES),
        "noise": _has(segment, NOISE_CUES),
        "attempted": False,
    }
    outage = _has(segment, OUTAGE_CUES)
    delay = _has(segment, DELAY_CUES)
    quality = _has(segment, QUALITY_CUES)
    if not (outage or delay or quality):
        return [], flags

    flags["attempted"] = True
    # Confirmed operational detail wins over rumor wording in the same sentence.
    mentions = world.match_mentions(segment)
    plants = _unique(mentions, "plant")
    parts = _unique(mentions, "part")
    suppliers = _unique(mentions, "supplier")
    for pid in _ids(r"\bP_[A-Z]{2}\b", segment):
        if pid in world.plants and pid not in plants:
            plants.append(pid)
    for part in _ids(r"\b[A-Z]{2,10}-\d{2,4}\b", segment):
        if part in world.parts and part not in parts:
            parts.append(part)
    for sid in _ids(r"\bSUP-\d+\b", segment):
        if sid in world.suppliers and sid not in suppliers:
            suppliers.append(sid)
    shipments = [s for s in _ids(r"\bSH-\d+\b", segment) if s in world.shipments]
    lots = [s for s in _ids(r"\bLOT-\d+\b", segment) if s in world.lots]
    dates = find_dates(segment)

    # Unconfirmed language with no complete binding falls through to escalate.
    built: list[dict] = []
    if outage:
        inc = _bind_outage(world, segment, plants, dates)
        if inc:
            built.append(inc)
    if delay and not built:
        inc = _bind_delay(world, segment, plants, parts, suppliers, shipments, dates)
        if inc:
            built.append(inc)
    if quality and not built:
        inc = _bind_quality(world, segment, plants, parts, suppliers, lots, dates)
        if inc:
            built.append(inc)
    if built:
        flags["attempted"] = False
        flags["unconfirmed"] = False
    return built, flags


def _bind_outage(world, segment, plants, dates) -> dict | None:
    if len(plants) != 1 or len(dates) < 2:
        return None
    start, end = dates[0]["date"], dates[1]["date"]
    if end < start:
        return None
    plant = plants[0]
    return {
        "kind": "plant_outage",
        "plant_id": plant,
        "start_date": start,
        "end_date": end,
        "start_idx": world.calendar[start]["idx"],
        "end_idx": world.calendar[end]["idx"],
        "ready_idx": world.calendar[end]["idx"] + 1,
        "evidence": [f"plant {plant}", dates[0]["phrase"], dates[1]["phrase"]],
        "span": segment[:400],
    }


def _bind_delay(world, segment, plants, parts, suppliers, shipments, dates) -> dict | None:
    if shipments:
        ship = world.shipments[shipments[0]]
        if len(dates) < 1:
            return None
        # The shipment row is the original ETA. The later date in the text is the new one.
        dated = [d["date"] for d in dates]
        new = dated[-1]
        if new <= ship["eta_date"]:
            return None
        if new not in world.calendar or ship["eta_date"] not in world.calendar:
            return None
        return _delay_from_ship(world, ship, new, segment, dates)
    if len(dates) < 2 or len(plants) != 1 or len(parts) != 1:
        return None
    old, new = dates[0]["date"], dates[1]["date"]
    if new <= old:
        return None
    cands = [
        s for s in world.shipments.values()
        if s["plant_id"] == plants[0]
        and s["part_id"] == parts[0]
        and s["eta_date"] == old
        and (not suppliers or s["supplier_id"] in suppliers)
    ]
    if len(cands) != 1:
        return None
    return _delay_from_ship(world, cands[0], new, segment, dates)


def _delay_from_ship(world, ship, new, segment, dates) -> dict:
    old = ship["eta_date"]
    return {
        "kind": "supplier_delay",
        "plant_id": ship["plant_id"],
        "part_id": ship["part_id"],
        "supplier_id": ship["supplier_id"],
        "shipment_id": ship["shipment_id"],
        "start_date": old,
        "end_date": new,
        "old_idx": world.calendar[old]["idx"],
        "new_idx": world.calendar[new]["idx"],
        "ready_idx": world.calendar[new]["idx"],
        "evidence": [ship["shipment_id"], ship["part_id"], old, new],
        "span": segment[:400],
    }


def _bind_quality(world, segment, plants, parts, suppliers, lots, dates) -> dict | None:
    if lots:
        lot = world.lots[lots[0]]
        return _quality_from_lot(lot, segment)
    if len(dates) < 2 or len(plants) != 1 or len(parts) != 1:
        return None
    first, last = dates[0]["date"], dates[1]["date"]
    if last < first:
        return None
    cands = [
        lot for lot in world.lots.values()
        if lot["plant_id"] == plants[0]
        and lot["part_id"] == parts[0]
        and lot["first_build_date"] == first
        and lot["last_build_date"] == last
        and (not suppliers or lot["supplier_id"] in suppliers)
    ]
    if len(cands) != 1:
        return None
    return _quality_from_lot(cands[0], segment)


def _quality_from_lot(lot, segment) -> dict:
    return {
        "kind": "quality_hold",
        "plant_id": lot["plant_id"],
        "part_id": lot["part_id"],
        "supplier_id": lot["supplier_id"],
        "lot_id": lot["lot_id"],
        "start_date": lot["first_build_date"],
        "end_date": lot["last_build_date"],
        "evidence": [lot["lot_id"], lot["part_id"], lot["first_build_date"], lot["last_build_date"]],
        "span": segment[:400],
    }


def incident_key(inc: dict) -> tuple:
    return (
        inc.get("kind"),
        inc.get("plant_id"),
        inc.get("part_id"),
        inc.get("supplier_id"),
        inc.get("shipment_id"),
        inc.get("lot_id"),
        inc.get("start_date"),
        inc.get("end_date"),
    )


def same_reading(a: dict, b: dict) -> bool:
    if a.get("disposition") != b.get("disposition"):
        return False
    ka = sorted(incident_key(i) for i in a.get("incidents", []))
    kb = sorted(incident_key(i) for i in b.get("incidents", []))
    return ka == kb
