#!/usr/bin/env python3
"""Plan every event, rehearse against the enterprise rules, then record the official action log.

From the package root:

    python3 solution/run.py                 # rehearse, serve, write runs/run1
    python3 solution/run.py --rehearse-only
    python3 solution/run.py --llm           # Llama 3.2 3B via local Ollama, no key
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "solution"))

from enterprise import WRITE_TOOLS, Enterprise  # noqa: E402

from tower.agents import Coordinator  # noqa: E402
from tower.execute import Gateway  # noqa: E402
from tower.llm import read_with_model  # noqa: E402
from tower.understand import parse_event  # noqa: E402
from tower.world import LAST_IDX, World, date_to_idx, idx_to_date  # noqa: E402
from datetime import date


def load_events(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def plan_all(world: World, events: list[dict], use_llm: bool) -> list[dict]:
    coord = Coordinator()
    traces = []
    for event in events:
        if use_llm:
            reading = read_with_model(world, event)
        else:
            reading = parse_event(world, event)
            reading["llm"] = {"used": False, "model": None, "agrees": None, "note": "model not called"}
        traces.append(coord.handle(world, event, reading))
    return traces


def _expected_loc(world: World, trace: dict) -> dict[str, tuple[str, int]]:
    loc = {
        po: (o["plant_id"], o["idx"])
        for po, o in world.orders.items()
        if o["idx"] >= 0
    }
    for move in trace["moves"]:
        po = move["production_order_id"]
        loc[po] = (move["to_plant"], date_to_idx(date.fromisoformat(move["to_date"])))
    return loc


def rehearse(world: World, traces: list[dict], data_dir: Path) -> list[str]:
    """Replay every planned call on a private Enterprise and check the handbook invariants."""
    problems = []
    ent = Enterprise(str(data_dir))
    gate = Gateway(world, None, enterprise=ent)
    for trace in traces:
        eid = trace["event_id"]
        if trace.get("incomplete"):
            problems.append(f"{eid} left an operational fragment unbound: {trace['incomplete']}")
        sent = []
        for action in trace["actions"]:
            result = gate.call(eid, action["tool"], action["args"])
            sent.append(result)
            if not result["ok"]:
                problems.append(f"{eid} {action['tool']} failed: {result['error']} args={action['args']}")
        if problems and problems[-1].startswith(eid):
            continue
        writes = [a for a in trace["actions"] if a["tool"] in WRITE_TOOLS]
        if trace["disposition"] == "noise":
            if trace["actions"]:
                problems.append(f"{eid} noise made a call")
            continue
        if trace["disposition"] == "unconfirmed":
            tools = [a["tool"] for a in trace["actions"]]
            if tools != ["escalate"] or writes:
                problems.append(f"{eid} unconfirmed calls were {tools}")
            state = ent.state(eid)
            if not state["escalated"]:
                problems.append(f"{eid} escalate did not stick")
            continue
        state = ent.state(eid)
        expected = _expected_loc(world, trace)
        if state["loc"] != expected:
            bad = [po for po in expected if state["loc"].get(po) != expected[po]]
            problems.append(f"{eid} location mismatch on {bad[:8]}")
        for key, occupants in state["slots"].items():
            plant, _idx = key
            if len(occupants) > world.plants[plant]["slots"]:
                problems.append(f"{eid} over capacity at {key}")
        notices = defaultdict(set)
        for action in trace["actions"]:
            if action["tool"] == "dealer.notify":
                notices[action["args"]["dealer_id"]].update(action["args"]["customer_order_ids"])
        got = {d: set(ids) for d, ids in state["notified"].items() if ids}
        if got != {d: ids for d, ids in notices.items() if ids}:
            problems.append(f"{eid} dealer notices do not match the replay")
        if len(notices) != sum(1 for a in trace["actions"] if a["tool"] == "dealer.notify"):
            problems.append(f"{eid} more than one notice for a dealer")
        loaned = {a["args"]["customer_order_id"] for a in trace["actions"] if a["tool"] == "crm.assign_loaner"}
        if state["loaned"] != loaned:
            problems.append(f"{eid} loaner set mismatch")
        held = {a["args"]["lot_id"] for a in trace["actions"] if a["tool"] == "quality.hold_lot"}
        if state["held"] != held:
            problems.append(f"{eid} held lots mismatch")
        stopped = set()
        for action in trace["actions"]:
            if action["tool"] == "dealer.stop_sale":
                stopped.update(action["args"]["vins"])
        if state["stopped"] != stopped:
            problems.append(f"{eid} stopped VINs mismatch")
        told = {a["args"]["customer_id"] for a in trace["actions"] if a["tool"] == "crm.notify_customer"}
        if state["customers"] != told:
            problems.append(f"{eid} customer notices mismatch")
        # Affected orders left the disruption window. Unaffected orders did not move.
        moved = {m["production_order_id"] for m in trace["moves"]}
        for inc in trace["incidents"]:
            if inc["kind"] == "plant_outage":
                for po, (plant, idx) in state["loc"].items():
                    if plant == inc["plant_id"] and inc["start_idx"] <= idx <= inc["end_idx"]:
                        problems.append(f"{eid} {po} still inside the outage")
                        break
            if inc["kind"] == "supplier_delay":
                models = world.part_models[inc["part_id"]]
                for po, (plant, idx) in state["loc"].items():
                    model = world.orders[po]["model"]
                    if plant == inc["plant_id"] and model in models and inc["old_idx"] <= idx < inc["new_idx"]:
                        problems.append(f"{eid} {po} still inside the delay window")
                        break
        for po, o in world.orders.items():
            if o["idx"] < 0 or po in moved:
                continue
            if state["loc"][po] != (o["plant_id"], o["idx"]):
                problems.append(f"{eid} moved unaffected {po}")
                break
        if not writes:
            problems.append(f"{eid} real incident produced no write")
        _ = LAST_IDX
    return problems


def _wait(url: str):
    for _ in range(80):
        try:
            with urllib.request.urlopen(url, timeout=1) as res:
                if res.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError(f"server did not come up at {url}")


def execute_http(world: World, traces: list[dict], base: str) -> int:
    gate = Gateway(world, base, enterprise=None)
    failed = 0
    for trace in traces:
        for action in trace["actions"]:
            result = gate.call(trace["event_id"], action["tool"], action["args"])
            action["ok"] = result["ok"]
            action["error"] = result["error"]
            action["result"] = result["result"]
            if not result["ok"]:
                failed += 1
    return failed


def ontology_export(world: World) -> dict:
    relations = []
    descriptions = {
        ("Supplier", "SHIPS", "Shipment"): "Supplier sends an inbound shipment.",
        ("Shipment", "CONTAINS", "Part"): "Shipment is one part number.",
        ("Shipment", "DELIVERED_TO", "Plant"): "Shipment is received at one plant. Only that plant's builds wait on it.",
        ("Part", "USED_IN", "Model"): "Bill of materials. A build needs the part when its model lists it.",
        ("Model", "CAN_BUILD_AT", "Plant"): "plant_models.csv. Transfers may only go to one of these plants.",
        ("ProductionOrder", "BUILT_AT", "Plant"): "Where the order is scheduled.",
        ("ProductionOrder", "OF_MODEL", "Model"): "Which model the order builds.",
        ("CustomerOrder", "FROM_BUILD", "ProductionOrder"): "A promised customer order is filled by one production order.",
        ("CustomerOrder", "AT_DEALER", "Dealer"): "The dealer who owns the customer relationship.",
        ("CustomerOrder", "FOR_CUSTOMER", "Customer"): "The buyer, with a service tier.",
        ("Lot", "OF_PART", "Part"): "Quality lot of one part.",
        ("Lot", "FROM_SUPPLIER", "Supplier"): "Who made the lot.",
        ("Lot", "AT_PLANT", "Plant"): "Where the lot was installed.",
        ("Vehicle", "FROM_BUILD", "ProductionOrder"): "Finished vehicle from a production order.",
        ("Vehicle", "AT_DEALER", "Dealer"): "Where an unsold vehicle can be stopped, or where it was sold.",
        ("Vehicle", "OWNED_BY", "Customer"): "Owner of a sold vehicle.",
    }
    for (src, edge, dst), count in sorted(world.edge_counts.items()):
        relations.append({
            "from": src, "edge": edge, "to": dst, "count": count,
            "meaning": descriptions.get((src, edge, dst), ""),
        })
    return {
        "today": "2027-03-08",
        "entities": [{"type": k, "count": v} for k, v in world.entity_counts().items()],
        "relations": relations,
        "paths": {
            "supplier_delay": "Shipment → Part → Model (BOM) → ProductionOrder → CustomerOrder → Dealer / Customer",
            "plant_outage": "Plant → ProductionOrder → CustomerOrder → Dealer / Customer",
            "quality_hold": "Lot → ProductionOrder → Vehicle → Dealer / Customer",
        },
    }


def write_outputs(out: Path, world: World, traces: list[dict], model_note: str):
    out.mkdir(parents=True, exist_ok=True)
    (out / "traces").mkdir(exist_ok=True)
    onto = ontology_export(world)
    (out / "ontology.json").write_text(json.dumps(onto, indent=2))
    public = []
    for trace in traces:
        # Drop nothing operational; the model proposal is part of the audit.
        (out / "traces" / f"{trace['event_id']}.json").write_text(json.dumps(trace, indent=2))
        public.append(trace)
    calls = sum(t["stats"]["tool_calls"] for t in traces)
    failed = sum(1 for t in traces for a in t["actions"] if a.get("ok") is False)
    report = {
        "meta": {
            "company": "Wacky Wheels Co.",
            "today": "2027-03-08",
            "model": model_note,
            "model_role": "Reads each event into incidents. Policy, graph walks, and tool arguments are deterministic code.",
            "n_events": len(traces),
            "n_tool_calls": calls,
            "n_failed": failed,
        },
        "ontology": onto,
        "events": public,
    }
    (out / "report.json").write_text(json.dumps(report))
    return report


def print_table(traces: list[dict]):
    print(f"{'event':<6} {'disposition':<12} {'categories':<32} {'moves':>5} {'xfer':>4} {'dealers':>7} {'loan':>5} {'lots':>4} {'stop':>5} {'owners':>6} {'calls':>5}")
    for t in traces:
        s = t["stats"]
        print(
            f"{t['event_id']:<6} {t['disposition']:<12} {', '.join(t['categories']):<32} "
            f"{s['reschedules'] + s['transfers']:>5} {s['transfers']:>4} {s['dealer_notices']:>7} "
            f"{s['loaners']:>5} {s['lots']:>4} {s['stop_sales']:>5} {s['customers']:>6} {s['tool_calls']:>5}"
        )
        if t["disposition"] == "act":
            for inc in t.get("incident_reports") or []:
                extra = inc.get("shipment_id") or inc.get("lot_id") or ""
                print(f"       {inc['label']}: {inc.get('plant_id')} {extra} {inc.get('start_date')} → {inc.get('end_date')} orders={len(inc.get('orders') or [])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--events", default=str(ROOT / "data" / "events.json"))
    ap.add_argument("--out", default=str(ROOT / "runs" / "run1"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--rehearse-only", action="store_true")
    ap.add_argument("--llm", action="store_true", help="Read each event with Llama 3.2 3B via Ollama, or OpenAI if OPENAI_API_KEY is set.")
    args = ap.parse_args()

    world = World(args.data)
    events = load_events(Path(args.events))
    traces = plan_all(world, events, use_llm=args.llm)
    print_table(traces)
    problems = rehearse(world, traces, Path(args.data))
    if problems:
        print("\nREHEARSAL FAILED")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print(f"\nRehearsal passed for {len(events)} events, 0 failed tool calls.")
    if args.rehearse_only:
        agreed = sum(1 for t in traces if (t.get("llm") or {}).get("agrees") is True)
        used = sum(1 for t in traces if (t.get("llm") or {}).get("used"))
        if args.llm:
            cited = next((t["llm"].get("model") for t in traces if (t.get("llm") or {}).get("model")), None)
            print(f"Model {cited}: used on {used}, agreed on {agreed}.")
        return

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "action_log.jsonl"
    if log_path.exists():
        log_path.unlink()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "enterprise_server.py"),
         "--data", args.data, "--events", args.events, "--out", str(out),
         "--port", str(args.port), "--overwrite"],
        cwd=str(ROOT),
    )
    base = f"http://127.0.0.1:{args.port}"
    try:
        _wait(base + "/events")
        failed = execute_http(world, traces, base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if failed:
        print(f"Server run had {failed} failed calls. Log left at {log_path} for inspection.")
        sys.exit(1)
    used = [t for t in traces if (t.get("llm") or {}).get("used")]
    cited = (used[0].get("llm") or {}).get("model") if used else None
    if not args.llm or not cited:
        model_note = "ontology reader (no model call this run)"
    else:
        agreed = sum(1 for t in used if (t.get("llm") or {}).get("agrees") is True)
        where = "on this Mac, no API key" if not os.environ.get("OPENAI_API_KEY") else "via API"
        model_note = (
            f"{cited} confirmed {agreed}/{len(traces)} readings {where}; "
            "actions follow the agreed ontology binding"
        )
    write_outputs(out, world, traces, model_note)
    lines = log_path.read_text().strip().splitlines()
    print(f"Wrote {len(lines)} calls to {log_path}")
    print(f"Report: {out / 'report.json'}")


if __name__ == "__main__":
    main()
