"""Tool gateway. Validates, then calls the enterprise server. A failed call is recorded and not retried."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .world import LAST_IDX, date_to_idx
from datetime import date


class ToolFailure(Exception):
    pass


def validate(world, tool: str, args: dict) -> str | None:
    """Return an error string when the call would be rejected. None means it is safe to send."""
    if not isinstance(args, dict):
        return "args must be an object"

    def day_ok(value: str) -> str | None:
        try:
            idx = date_to_idx(date.fromisoformat(value))
        except (TypeError, ValueError):
            return "date must be a weekday YYYY-MM-DD"
        if not 0 <= idx <= LAST_IDX:
            return "date outside the planning window"
        return None

    if tool == "mes.reschedule":
        po = args.get("production_order_id")
        if po not in world.orders or world.orders[po]["idx"] < 0:
            return "unknown or already built production order"
        return day_ok(args.get("new_date"))
    if tool == "mes.transfer":
        po, plant = args.get("production_order_id"), args.get("to_plant_id")
        if po not in world.orders or world.orders[po]["idx"] < 0:
            return "unknown or already built production order"
        if plant not in world.plants or world.orders[po]["model"] not in world.plants[plant]["models"]:
            return "that plant does not build this model"
        if plant == world.orders[po]["plant_id"]:
            return "use mes.reschedule inside the same plant"
        return day_ok(args.get("new_date"))
    if tool == "dealer.notify":
        dealer, ids = args.get("dealer_id"), args.get("customer_order_ids")
        if dealer not in world.dealers:
            return "unknown dealer"
        if not isinstance(ids, list) or not ids:
            return "customer_order_ids must be a non-empty list"
        if not args.get("message"):
            return "message required"
        bad = [i for i in ids if i not in world.customer_orders or world.customer_orders[i]["dealer_id"] != dealer]
        return f"orders not at {dealer}: {bad[:3]}" if bad else None
    if tool == "dealer.stop_sale":
        dealer, vins = args.get("dealer_id"), args.get("vins")
        if dealer not in world.dealers:
            return "unknown dealer"
        if not isinstance(vins, list) or not vins:
            return "vins must be a non-empty list"
        bad = [
            v for v in vins
            if v not in world.vehicles or world.vehicles[v]["dealer_id"] != dealer or world.vehicles[v]["status"] != "in_stock"
        ]
        return f"not unsold at {dealer}: {bad[:3]}" if bad else None
    if tool == "crm.loaner_availability":
        if args.get("dealer_id") not in world.loaners:
            return "unknown dealer"
        return None
    if tool == "crm.assign_loaner":
        co = args.get("customer_order_id")
        if co not in world.customer_orders:
            return "unknown customer order"
        return None
    if tool == "crm.notify_customer":
        if args.get("customer_id") not in world.customers:
            return "unknown customer"
        if not args.get("message"):
            return "message required"
        return None
    if tool == "quality.hold_lot":
        if args.get("lot_id") not in world.lots:
            return "unknown lot"
        return None
    if tool == "escalate":
        if not args.get("reason"):
            return "reason required"
        return None
    if tool == "mes.get_schedule":
        if args.get("plant_id") not in world.plants:
            return "unknown plant"
        return day_ok(args.get("date"))
    return "unknown tool"


class Gateway:
    def __init__(self, world, base_url: str | None, enterprise=None):
        self.world = world
        self.base_url = base_url.rstrip("/") if base_url else None
        self.enterprise = enterprise
        self.remaining_loaners: dict[tuple[str, str], int | None] = {}

    def call(self, event_id: str, tool: str, args: dict) -> dict:
        problem = validate(self.world, tool, args)
        if problem:
            return {"ok": False, "error": f"blocked before send: {problem}", "result": None, "sent": False}
        if tool == "crm.assign_loaner":
            co = args["customer_order_id"]
            dealer = self.world.customer_orders[co]["dealer_id"]
            left = self.remaining_loaners.get((event_id, dealer))
            if left is not None and left <= 0:
                return {"ok": False, "error": "skipped: loaner pool already empty", "result": None, "sent": False}
        try:
            result = self._send(event_id, tool, args)
        except ToolFailure as exc:
            return {"ok": False, "error": str(exc), "result": None, "sent": True}
        if tool == "crm.loaner_availability":
            self.remaining_loaners[(event_id, args["dealer_id"])] = int(result["available"])
        if tool == "crm.assign_loaner":
            dealer = self.world.customer_orders[args["customer_order_id"]]["dealer_id"]
            key = (event_id, dealer)
            if self.remaining_loaners.get(key) is not None:
                self.remaining_loaners[key] -= 1
        return {"ok": True, "error": None, "result": result, "sent": True}

    def _send(self, event_id, tool, args):
        if self.enterprise is not None:
            try:
                return self.enterprise.call(event_id, tool, args)
            except Exception as exc:
                raise ToolFailure(str(exc)) from exc
        body = json.dumps({"event_id": event_id, "tool": tool, "args": args}).encode()
        req = urllib.request.Request(
            self.base_url + "/act",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()
            try:
                detail = json.loads(detail).get("error", detail)
            except json.JSONDecodeError:
                pass
            raise ToolFailure(detail) from exc
