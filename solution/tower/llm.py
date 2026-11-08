"""One small-model call per event. It proposes a reading; it never calls a tool."""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

from .understand import find_dates, parse_event, same_reading
from .world import World

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
LOCAL_MODEL = os.environ.get("HACK_HIGHWAY_LOCAL_MODEL", "llama3.2:3b")
OPENAI_MODEL = os.environ.get("HACK_HIGHWAY_MODEL", "gpt-4.1-mini")
# Cited name for this process. propose() sets it to whichever backend actually ran.
MODEL = OPENAI_MODEL

SYSTEM = """You extract incidents from one operations message for Wacky Wheels Co.
Today is Monday 2027-03-08. Do not choose actions and do not invent ids that are not written in the message.
Copy plant, part, supplier, and date phrases verbatim from the message.

disposition:
- "act" when the message states a confirmed plant outage, supplier delay, or quality hold
- "noise" when it is not about factory operations (brochure, price list, unrelated ask)
- "unconfirmed" when it is a rumor or it lacks dates and a specific shipment, lot, or plant window

kind is one of plant_outage, supplier_delay, quality_hold.
A message can contain more than one incident. Return every one, in order.
dates is a list of the date phrases in the order they appear, copied exactly
(for example "next Friday", "Monday Mar 22", "2027-03-15", "last Monday").
shipment_id and lot_id are copied only when the message contains SH-#### or LOT-####.
Return JSON only:
{"disposition":"act|noise|unconfirmed","incidents":[{"kind":"","plant":"","part":"","supplier":"","shipment_id":"","lot_id":"","dates":[]}]}
"""


def _key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return key or None


def propose(event: dict) -> dict | None:
    """OpenAI when a key is set. Otherwise the local Ollama model, which needs no key."""
    if _key():
        return _propose_openai(event)
    return _propose_ollama(event)


def _propose_openai(event: dict) -> dict | None:
    global MODEL
    key = _key()
    MODEL = OPENAI_MODEL
    payload = {
        "model": MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": event["text"]},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45, context=_ssl_context()) as res:
            body = json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except json.JSONDecodeError:
            detail = detail[:300]
        return {"error": f"HTTP {exc.code}: {detail}", "model": MODEL}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": str(exc), "model": MODEL}
    try:
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        return {"error": f"bad model payload: {exc}", "model": MODEL}
    parsed["model"] = MODEL
    return parsed


def _json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _propose_ollama(event: dict) -> dict:
    """Local model. No API key and no cloud call."""
    global MODEL
    MODEL = LOCAL_MODEL
    payload = {
        "model": LOCAL_MODEL,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": event["text"]},
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            body = json.loads(res.read().decode())
        parsed = _json_object(body["message"]["content"])
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        return {"error": str(exc), "model": LOCAL_MODEL}
    if not isinstance(parsed, dict):
        return {"error": "model did not return an object", "model": LOCAL_MODEL}
    parsed["model"] = LOCAL_MODEL
    return parsed


def _disposition(value) -> str | None:
    """Accept a real label. 'act|act' is the schema echoed twice, so it is act.

    A mixed echo such as 'act|noise|unconfirmed' is not a decision and stays unbound.
    """
    if not isinstance(value, str):
        return None
    parts = [p.strip() for p in value.split("|") if p.strip()]
    if len(parts) == 1 and parts[0] in ("act", "noise", "unconfirmed"):
        return parts[0]
    if len(parts) > 1 and len(set(parts)) == 1 and parts[0] in ("act", "noise", "unconfirmed"):
        return parts[0]
    return None


def bind_proposal(world: World, proposal: dict) -> dict | None:
    """Resolve the model's phrases with the same gazetteer and calendar as the rule reader."""
    if not proposal or proposal.get("error"):
        return None
    disposition = _disposition(proposal.get("disposition"))
    if disposition is None:
        return None
    incidents = []
    if disposition == "act":
        for raw in proposal.get("incidents") or []:
            if not isinstance(raw, dict):
                return None
            # Re-parse a compact sentence built only from the phrases the model copied,
            # then keep the binding only if it matches that kind.
            bits = [
                str(raw.get("kind") or ""),
                str(raw.get("plant") or ""),
                str(raw.get("part") or ""),
                str(raw.get("supplier") or ""),
                str(raw.get("shipment_id") or ""),
                str(raw.get("lot_id") or ""),
                " ".join(raw.get("dates") or []),
            ]
            kind = raw.get("kind")
            cue = {
                "plant_outage": "plant outage. Production is stopped from",
                "supplier_delay": "shipment delayed. Original drop was",
                "quality_hold": "quality alert. Anything built",
            }.get(kind)
            if cue is None:
                return None
            synthetic = {
                "text": cue + " " + " ".join(b for b in bits if b) + " through " + " ".join(raw.get("dates") or []),
            }
            # "through" duplicated dates would confuse the binder. Bind fields directly.
            bound = _bind_fields(world, raw)
            if bound is None:
                return None
            incidents.append(bound)
            _ = synthetic
    return {"disposition": disposition, "incidents": incidents, "reader": "llm"}


def _bind_fields(world: World, raw: dict) -> dict | None:
    """Bind one model incident by resolving the phrases it copied out of the message."""
    from .understand import _bind_delay, _bind_outage, _bind_quality

    kind = raw.get("kind")
    plant_text = str(raw.get("plant") or "")
    part_text = str(raw.get("part") or "")
    supplier_text = str(raw.get("supplier") or "")
    ship_ids = []
    lot_ids = []
    sid = str(raw.get("shipment_id") or "").upper()
    lid = str(raw.get("lot_id") or "").upper()
    if sid in world.shipments:
        ship_ids = [sid]
    if lid in world.lots:
        lot_ids = [lid]
    blob = " ".join([plant_text, part_text, supplier_text, sid, lid, " ".join(raw.get("dates") or [])])
    mentions = world.match_mentions(blob)
    plants, parts, suppliers = [], [], []
    for typ, eid, _phrase in mentions:
        bucket = {"plant": plants, "part": parts, "supplier": suppliers}.get(typ)
        if bucket is not None and eid not in bucket:
            bucket.append(eid)
    dates = find_dates(" ".join(raw.get("dates") or []))
    # Also accept ISO dates the model normalized, via find_dates on the date list.
    if kind == "plant_outage":
        return _bind_outage(world, blob, plants, dates)
    if kind == "supplier_delay":
        # Two dates are required when the shipment id is absent; with an id, the
        # last date is the new ETA. _bind_delay handles both.
        return _bind_delay(world, blob, plants, parts, suppliers, ship_ids, dates)
    if kind == "quality_hold":
        return _bind_quality(world, blob, plants, parts, suppliers, lot_ids, dates)
    return None


def read_with_model(world: World, event: dict) -> dict:
    """Ontology reader is authoritative when the model is absent or unbound.

    When the model binds to the same incidents, that agreed reading is what we execute.
    """
    rule = parse_event(world, event)
    proposal = propose(event)
    if proposal is None:
        rule["llm"] = {"used": False, "model": None, "agrees": None, "note": "OPENAI_API_KEY not set"}
        return rule
    if proposal.get("error"):
        rule["llm"] = {"used": False, "model": MODEL, "agrees": None, "note": proposal["error"], "proposal": proposal}
        return rule
    bound = bind_proposal(world, proposal)
    agrees = bool(bound) and same_reading(rule, bound)
    rule["llm"] = {
        "used": True,
        "model": MODEL,
        "agrees": agrees,
        "proposal": proposal,
        "note": "model and ontology reader agree" if agrees else "ontology reader kept; model reading did not bind to the same incidents",
    }
    if agrees and bound is not None:
        # Same incidents, sourced from the confirmed model reading.
        bound["llm"] = rule["llm"]
        bound["incomplete"] = rule.get("incomplete", [])
        return bound
    return rule
