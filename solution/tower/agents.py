"""Coordinator plus three specialists. The model never reaches a tool from here."""
from __future__ import annotations

from .policy import Schedule, loaner_ranking, notify_groups
from .world import idx_to_date, iso

SUPPLY = "Supply Chain Planner"
QUALITY = "Quality Sentinel"
DESK = "Dealer & Customer Desk"
COORD = "Coordinator"

WRITE_TOOLS = {
    "mes.reschedule", "mes.transfer", "dealer.notify", "dealer.stop_sale",
    "crm.assign_loaner", "crm.notify_customer", "quality.hold_lot",
}
LABEL = {
    "plant_outage": "Plant outage",
    "supplier_delay": "Supplier delay",
    "quality_hold": "Quality hold",
}


class SupplyChainPlanner:
    name = SUPPLY

    def plan(self, world, schedule: Schedule, incident: dict, all_incidents: list[dict]) -> dict:
        if incident["kind"] == "plant_outage":
            pos = world.outage_window(incident["plant_id"], incident["start_idx"], incident["end_idx"])
            paths = world.cite_outage(incident["plant_id"], pos)
            ready = incident["ready_idx"]
            restart = iso(idx_to_date(ready)) if ready <= 19 else "after the planning window"
            narrative = (
                f"Walked Plant {incident['plant_id']} → production orders scheduled "
                f"{incident['start_date']} through {incident['end_date']} inclusive. "
                f"{len(pos)} orders cannot build during the outage. The line restarts {restart}. "
                f"Rule 2 and rule 3."
            )
        else:
            pos = world.delay_window(
                incident["plant_id"], incident["part_id"], incident["old_idx"], incident["new_idx"],
            )
            paths = world.cite_delay(incident["shipment_id"], pos)
            models = sorted(world.part_models[incident["part_id"]])
            narrative = (
                f"Walked {incident['shipment_id']} → {incident['part_id']} → "
                f"{', '.join(models)} (bill of materials) → production orders at "
                f"{incident['plant_id']} from {incident['start_date']} up to {incident['end_date']}. "
                f"{len(pos)} orders need the delayed part. Rule 1 and rule 3."
            )
        prefix = narrative
        moves = schedule.place(pos, incident["ready_idx"], all_incidents, prefix)
        same = sum(1 for m in moves if m["tool"] == "mes.reschedule")
        xfer = len(moves) - same
        narrative += f" Placed {same} at the same plant and transferred {xfer}."
        reason = _short_reason(world, incident)
        return {
            "po_ids": pos,
            "paths": paths,
            "moves": moves,
            "narrative": narrative,
            "reason": reason,
            "models": sorted({world.orders[po]["model"] for po in pos}),
        }


class QualitySentinel:
    name = QUALITY

    def plan(self, world, event: dict, incident: dict) -> dict:
        lot = world.lots[incident["lot_id"]]
        vehicles = world.vehicles_for_lot(lot)
        paths = world.cite_quality(lot, vehicles)
        part = world.part_name(lot["part_id"])
        actions = [{
            "agent": QUALITY,
            "tool": "quality.hold_lot",
            "args": {"lot_id": lot["lot_id"]},
            "why": (
                f"Lot {lot['lot_id']} ({part}, {lot['supplier_id']}) at {lot['plant_id']} "
                f"covers builds {lot['first_build_date']} through {lot['last_build_date']}. Rule 6."
            ),
        }]
        unsold: dict[str, list[str]] = {}
        owners = []
        for v in vehicles:
            if v["status"] == "in_stock":
                unsold.setdefault(v["dealer_id"], []).append(v["vin"])
            elif v["status"] == "sold" and v["customer_id"]:
                owners.append(v["customer_id"])
        for dealer in sorted(unsold):
            vins = sorted(set(unsold[dealer]))
            actions.append({
                "agent": QUALITY,
                "tool": "dealer.stop_sale",
                "args": {"dealer_id": dealer, "vins": vins},
                "why": f"Stop sale of {len(vins)} unsold vehicle(s) at {dealer} from lot {lot['lot_id']}. Rule 6.",
            })
        message = (
            f"{event['event_id']}: quality hold on lot {lot['lot_id']} ({part}). "
            "A vehicle you own was built with this lot. Please contact your dealer."
        )
        for cid in sorted(set(owners)):
            actions.append({
                "agent": QUALITY,
                "tool": "crm.notify_customer",
                "args": {"customer_id": cid, "message": message},
                "why": f"Owner {cid} has a sold vehicle from lot {lot['lot_id']}. Rule 6.",
            })
        narrative = (
            f"Walked {lot['lot_id']} → production orders of models that use {lot['part_id']} "
            f"→ vehicles built at {lot['plant_id']} from {lot['first_build_date']} through "
            f"{lot['last_build_date']}. {len(vehicles)} vehicles: "
            f"{sum(len(v) for v in unsold.values())} unsold, {len(set(owners))} owners. Rule 6."
        )
        return {"actions": actions, "paths": paths, "narrative": narrative, "vehicles": len(vehicles)}


class DealerCustomerDesk:
    name = DESK

    def plan(self, world, event: dict, customer_orders: list[dict], po_reason: dict[str, str]) -> dict:
        actions = []
        groups = notify_groups(customer_orders)
        for dealer in sorted(groups):
            ids = groups[dealer]
            reasons = sorted({po_reason.get(world.customer_orders[i]["production_order_id"], "a schedule change") for i in ids})
            actions.append({
                "agent": DESK,
                "tool": "dealer.notify",
                "args": {
                    "dealer_id": dealer,
                    "customer_order_ids": ids,
                    "message": (
                        f"{event['event_id']}: timing changed for the listed customer orders "
                        f"({'; '.join(reasons)}). Builds move to the earliest feasible slot. "
                        "This notice lists only those orders."
                    ),
                },
                "why": f"One notice to {dealer} for {len(ids)} affected customer order(s). Rule 4.",
            })
        ranked = loaner_ranking(world, customer_orders)
        assigned = []
        skipped = []
        for dealer in sorted(ranked):
            entitled = ranked[dealer]
            pool = world.loaners.get(dealer, 0)
            actions.append({
                "agent": DESK,
                "tool": "crm.loaner_availability",
                "args": {"dealer_id": dealer},
                "why": f"Pool check before assigning loaners at {dealer} ({pool} on the book, {len(entitled)} entitled).",
            })
            for co in entitled[:pool]:
                tier = world.customers[co["customer_id"]]["tier"]
                actions.append({
                    "agent": DESK,
                    "tool": "crm.assign_loaner",
                    "args": {"customer_order_id": co["customer_order_id"]},
                    "why": (
                        f"{tier} order {co['customer_order_id']} (promised {co['promised_date']}) "
                        f"is inside {dealer}'s pool of {pool}. Rule 5."
                    ),
                })
                assigned.append(co["customer_order_id"])
            for co in entitled[pool:]:
                skipped.append(co["customer_order_id"])
        narrative = (
            f"Rule 4: {len(groups)} dealer notice(s), one each, listing only affected customer orders. "
            f"Rule 5: {len(assigned)} loaner(s) for Platinum and Gold in priority order; "
            f"{len(skipped)} entitled order(s) left without a car because the pool ran out. "
            "Standard customers are on the dealer notice only."
        )
        return {"actions": actions, "narrative": narrative, "assigned": assigned, "skipped": skipped}


class Coordinator:
    name = COORD

    def __init__(self):
        self.supply = SupplyChainPlanner()
        self.quality = QualitySentinel()
        self.desk = DealerCustomerDesk()

    def handle(self, world, event: dict, reading: dict) -> dict:
        disposition = reading["disposition"]
        base = {
            "event_id": event["event_id"],
            "received_at": event.get("received_at"),
            "source": event.get("source"),
            "text": event["text"],
            "disposition": disposition,
            "llm": reading.get("llm") or {"used": False, "model": None, "agrees": None, "note": ""},
            "incidents": reading.get("incidents") or [],
            "incomplete": reading.get("incomplete") or [],
        }
        if disposition == "noise":
            return self._quiet(world, base, event, noise=True)
        if disposition == "unconfirmed":
            return self._quiet(world, base, event, noise=False)
        return self._act(world, base, event, reading["incidents"])

    def _quiet(self, world, base, event, noise: bool) -> dict:
        if noise:
            summary = (
                f"{event['event_id']} is noise. It does not describe a shipment, an outage, "
                "a quality lot, or any other factory incident, so no tool is called."
            )
            reasoning = (
                "Rule 7: unrelated messages get no operational action. "
                f"Source is {event.get('source')}. The text asks about something outside the control tower "
                f"(\"{_clip(event['text'])}\"). Specialists were not dispatched. Nothing was written."
            )
            categories = ["Noise"]
            actions = []
            handoffs = [
                {"agent": COORD, "did": "Classified the message as noise and stood the specialists down."},
            ]
            guardrails = [
                "No write tools called.",
                "escalate was not used; the message is irrelevant, not an unclear operations report.",
            ]
        else:
            reason = (
                f"{event['event_id']} is an unconfirmed or incomplete report "
                f"(\"{_clip(event['text'])}\"). No plant window, shipment, or lot is specific enough to act on."
            )
            summary = reason + " Escalated to a human. No operational change."
            reasoning = (
                "Rule 8: if a report is not specific or confirmed, escalate and do not change production, "
                "dealers, loaners, lots, or customers. " + reason
            )
            categories = ["Unconfirmed report"]
            actions = [{
                "agent": COORD,
                "tool": "escalate",
                "args": {"reason": reason},
                "why": "Human-in-the-loop. The handbook forbids a guess.",
            }]
            handoffs = [
                {"agent": COORD, "did": "Judged the report not actionable and escalated. Specialists made no changes."},
            ]
            guardrails = [
                "Only escalate is called.",
                "No reschedule, transfer, dealer, loaner, lot, or customer write.",
            ]
        return {
            **base,
            "categories": categories,
            "summary": summary,
            "reasoning": reasoning,
            "handoffs": handoffs,
            "guardrails": guardrails,
            "paths": [],
            "moves": [],
            "actions": actions,
            "stats": _stats(actions, categories),
        }

    def _act(self, world, base, event, incidents: list[dict]) -> dict:
        schedule = Schedule(world)
        handoffs = [{
            "agent": COORD,
            "did": f"Split the message into {len(incidents)} incident(s) and dispatched specialists.",
        }]
        paths = []
        moves = []
        actions = []
        narratives = []
        po_reason: dict[str, str] = {}
        affected: list[str] = []
        incident_reports = []

        for inc in incidents:
            if inc["kind"] in ("plant_outage", "supplier_delay"):
                planned = self.supply.plan(world, schedule, inc, incidents)
                handoffs.append({"agent": SUPPLY, "did": planned["narrative"]})
                narratives.append(planned["narrative"])
                for po in planned["po_ids"]:
                    po_reason[po] = planned["reason"]
                    affected.append(po)
                moves.extend(planned["moves"])
                paths.append({
                    "incident": LABEL[inc["kind"]],
                    "pattern": (
                        "Shipment → Part → Model (BOM) → ProductionOrder → CustomerOrder → Dealer / Customer"
                        if inc["kind"] == "supplier_delay"
                        else "Plant → ProductionOrder → CustomerOrder → Dealer / Customer"
                    ),
                    "walk": planned["narrative"],
                    "chains": [p["chain"] for p in planned["paths"]],
                })
                incident_reports.append({
                    "kind": inc["kind"],
                    "label": LABEL[inc["kind"]],
                    "plant_id": inc.get("plant_id"),
                    "part_id": inc.get("part_id"),
                    "shipment_id": inc.get("shipment_id"),
                    "lot_id": inc.get("lot_id"),
                    "start_date": inc.get("start_date"),
                    "end_date": inc.get("end_date"),
                    "orders": planned["po_ids"],
                    "models": planned["models"],
                    "narrative": planned["narrative"],
                })
            elif inc["kind"] == "quality_hold":
                planned = self.quality.plan(world, event, inc)
                handoffs.append({"agent": QUALITY, "did": planned["narrative"]})
                narratives.append(planned["narrative"])
                actions.extend(planned["actions"])
                paths.append({
                    "incident": LABEL[inc["kind"]],
                    "pattern": "Lot → ProductionOrder → Vehicle → Dealer / Customer",
                    "walk": planned["narrative"],
                    "chains": [p["chain"] for p in planned["paths"]],
                })
                incident_reports.append({
                    "kind": inc["kind"],
                    "label": LABEL[inc["kind"]],
                    "plant_id": inc.get("plant_id"),
                    "part_id": inc.get("part_id"),
                    "shipment_id": None,
                    "lot_id": inc.get("lot_id"),
                    "start_date": inc.get("start_date"),
                    "end_date": inc.get("end_date"),
                    "orders": sorted({step.split(" → ")[1] for step in (p["chain"] for p in planned["paths"])}) if planned["paths"] else [],
                    "models": sorted(world.part_models[inc["part_id"]]),
                    "narrative": planned["narrative"],
                })

        move_actions = [{
            "agent": SUPPLY,
            "tool": m["tool"],
            "args": m["args"],
            "why": m["why"],
        } for m in moves]
        quality_actions = [a for a in actions]
        customer_orders = []
        seen = set()
        for po in affected:
            for cid in world.pos_to_cos.get(po, []):
                if cid not in seen:
                    seen.add(cid)
                    customer_orders.append(world.customer_orders[cid])
        desk = {"actions": [], "narrative": "No customer orders sit on the affected builds.", "assigned": [], "skipped": []}
        if customer_orders:
            desk = self.desk.plan(world, event, customer_orders, po_reason)
            handoffs.append({"agent": DESK, "did": desk["narrative"]})
            narratives.append(desk["narrative"])
        elif any(i["kind"] != "quality_hold" for i in incidents):
            handoffs.append({"agent": DESK, "did": "No affected customer orders, so no dealer notice and no loaner."})

        actions = move_actions + quality_actions + desk["actions"]
        categories = [LABEL[i["kind"]] for i in incidents]
        summary = _summary(event, categories, moves, desk, quality_actions)
        reasoning = " ".join(narratives)
        reasoning += (
            " Guardrail: only orders, vehicles, dealers, and customers reached by the walk are touched. "
            "Shared slots and loaner pools are one board for the whole event, so a compound message cannot double-book them."
        )
        kinds = sorted({a["tool"] for a in actions if a["tool"] in WRITE_TOOLS})
        guardrails = [
            "Every id was resolved through the ontology before a tool was built.",
            "Unaffected production orders are left on their original day.",
            f"Write tools used: {', '.join(kinds) if kinds else 'none'}.",
        ]
        if len(kinds) < 3 and any(i["kind"] != "quality_hold" for i in incidents):
            guardrails.append("Fewer than three write kinds because the data did not support another one (no entitled loaner, or no customer order).")
        return {
            **base,
            "categories": categories,
            "summary": summary,
            "reasoning": reasoning,
            "handoffs": handoffs,
            "guardrails": guardrails,
            "paths": paths,
            "moves": moves,
            "actions": actions,
            "incident_reports": incident_reports,
            "stats": _stats(actions, categories),
        }


def _short_reason(world, inc: dict) -> str:
    if inc["kind"] == "plant_outage":
        return f"outage at {inc['plant_id']} {inc['start_date']} through {inc['end_date']}"
    return (
        f"delay of {world.part_name(inc['part_id'])} ({inc['shipment_id']}) into {inc['plant_id']}, "
        f"now due {inc['end_date']}"
    )


def _summary(event, categories, moves, desk, quality_actions) -> str:
    bits = [f"{event['event_id']} is {', '.join(categories)}."]
    if moves:
        xfer = sum(1 for m in moves if m["tool"] == "mes.transfer")
        bits.append(f"{len(moves)} production orders move ({len(moves) - xfer} rescheduled, {xfer} transferred).")
    holds = sum(1 for a in quality_actions if a["tool"] == "quality.hold_lot")
    stops = sum(1 for a in quality_actions if a["tool"] == "dealer.stop_sale")
    owners = sum(1 for a in quality_actions if a["tool"] == "crm.notify_customer")
    if holds:
        bits.append(f"{holds} lot(s) held, {stops} dealer stop-sale call(s), {owners} owner(s) contacted.")
    notes = sum(1 for a in desk["actions"] if a["tool"] == "dealer.notify")
    loans = len(desk["assigned"])
    if notes or loans:
        bits.append(f"{notes} dealer notice(s) and {loans} loaner assignment(s).")
    return " ".join(bits)


def _stats(actions, categories) -> dict:
    def n(tool):
        return sum(1 for a in actions if a["tool"] == tool)
    return {
        "categories": categories,
        "tool_calls": len(actions),
        "reschedules": n("mes.reschedule"),
        "transfers": n("mes.transfer"),
        "dealer_notices": n("dealer.notify"),
        "loaner_checks": n("crm.loaner_availability"),
        "loaners": n("crm.assign_loaner"),
        "lots": n("quality.hold_lot"),
        "stop_sales": n("dealer.stop_sale"),
        "customers": n("crm.notify_customer"),
        "escalations": n("escalate"),
        "write_kinds": sorted({a["tool"] for a in actions if a["tool"] in WRITE_TOOLS}),
    }


def _clip(text: str, limit: int = 180) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
