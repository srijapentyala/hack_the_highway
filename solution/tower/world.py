"""Company ontology. Every id the agents act on is reached by walking this graph."""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date, timedelta

TODAY = date(2027, 3, 8)  # Monday, working-day index 0
LAST_IDX = 19             # 2027-04-02, last planning day the tools accept
TIER_RANK = {"Platinum": 0, "Gold": 1, "Standard": 2}
LOANER_TIERS = ("Platinum", "Gold")


def idx_to_date(i: int) -> date:
    return TODAY + timedelta(days=7 * (i // 5) + i % 5)


def date_to_idx(d: date) -> int:
    days = (d - TODAY).days
    if days % 7 > 4:
        raise ValueError(f"weekend: {d.isoformat()}")
    return 5 * (days // 7) + days % 7


def iso(d: date) -> str:
    return d.isoformat()


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class World:
    """Indexes plus an explicit node/edge graph so traversals can be cited."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        rd = lambda name: read_csv(os.path.join(data_dir, name))

        self.plant_order: list[str] = []
        self.plants: dict[str, dict] = {}
        for r in rd("plants.csv"):
            self.plant_order.append(r["plant_id"])
            self.plants[r["plant_id"]] = {
                "plant_id": r["plant_id"],
                "name": r["name"],
                "city": r["city"],
                "slots": int(r["slots_per_day"]),
                "models": set(),
            }
        for r in rd("plant_models.csv"):
            self.plants[r["plant_id"]]["models"].add(r["model"])

        self.models = {r["model"]: r for r in rd("models.csv")}
        self.parts = {r["part_id"]: r for r in rd("parts.csv")}
        self.suppliers = {r["supplier_id"]: r for r in rd("suppliers.csv")}
        self.dealers = {r["dealer_id"]: r for r in rd("dealers.csv")}
        self.customers = {r["customer_id"]: r for r in rd("customers.csv")}

        self.orders: dict[str, dict] = {}
        for r in rd("production_orders.csv"):
            d = date.fromisoformat(r["build_date"])
            self.orders[r["production_order_id"]] = {
                "production_order_id": r["production_order_id"],
                "plant_id": r["plant_id"],
                "build_date": r["build_date"],
                "idx": date_to_idx(d),
                "model": r["model"],
                "units": int(r["units"]),
            }

        self.customer_orders: dict[str, dict] = {}
        self.pos_to_cos: dict[str, list[str]] = defaultdict(list)
        for r in rd("customer_orders.csv"):
            self.customer_orders[r["customer_order_id"]] = r
            self.pos_to_cos[r["production_order_id"]].append(r["customer_order_id"])
        for ids in self.pos_to_cos.values():
            ids.sort()

        self.shipments = {r["shipment_id"]: r for r in rd("inbound_shipments.csv")}
        self.lots = {r["lot_id"]: r for r in rd("part_lots.csv")}
        self.loaners = {r["dealer_id"]: int(r["loaners_available"]) for r in rd("loaners.csv")}

        self.vehicles = {r["vin"]: r for r in rd("finished_vehicles.csv")}
        self.bom: dict[str, set[str]] = defaultdict(set)          # model -> parts
        self.part_models: dict[str, set[str]] = defaultdict(set)  # part -> models
        for r in rd("bom.csv"):
            self.bom[r["model"]].add(r["part_id"])
            self.part_models[r["part_id"]].add(r["model"])

        self.calendar = {}
        for r in rd("calendar.csv"):
            self.calendar[r["date"]] = {"idx": int(r["day_index"]), "weekday": r["weekday"]}

        self.aliases: list[tuple[str, str, str]] = []
        seen = set()

        def add_alias(phrase: str, typ: str, eid: str):
            key = (phrase.strip().lower(), typ, eid)
            if not key[0] or key in seen:
                return
            seen.add(key)
            self.aliases.append(key)

        for r in rd("aliases.csv"):
            add_alias(r["alias"], r["entity_type"], r["entity_id"])
        for pid, p in self.plants.items():
            add_alias(p["name"], "plant", pid)
            add_alias(pid, "plant", pid)
        for pid, p in self.parts.items():
            add_alias(p["name"], "part", pid)
            add_alias(pid, "part", pid)
        for sid, s in self.suppliers.items():
            add_alias(s["name"], "supplier", sid)
            add_alias(sid, "supplier", sid)
        for mid in self.models:
            add_alias(mid, "model", mid)
            add_alias(mid.title(), "model", mid)
        # A copied state word ("Texas", "Kentucky") is the plant when that word
        # belongs to exactly one plant alias. Longer phrases still win below.
        stop = {"the", "plant", "wacky", "wheels", "north", "south", "east", "west"}
        owners: dict[str, set[str]] = defaultdict(set)
        for phrase, typ, eid in self.aliases:
            if typ != "plant":
                continue
            for word in phrase.split():
                if len(word) < 5 or word in stop:
                    continue
                owners[word].add(eid)
        for word, ids in owners.items():
            if len(ids) == 1:
                add_alias(word, "plant", next(iter(ids)))
        # Longest phrase wins so "heavy-duty wiring harness" beats a shorter overlap.
        self.aliases.sort(key=lambda a: len(a[0]), reverse=True)

        self.edge_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self._tally_edges()

    def _tally_edges(self):
        e = self.edge_counts
        for s in self.shipments.values():
            e[("Supplier", "SHIPS", "Shipment")] += 1
            e[("Shipment", "CONTAINS", "Part")] += 1
            e[("Shipment", "DELIVERED_TO", "Plant")] += 1
        for model, parts in self.bom.items():
            e[("Part", "USED_IN", "Model")] += len(parts)
        for p in self.plants.values():
            e[("Model", "CAN_BUILD_AT", "Plant")] += len(p["models"])
        e[("ProductionOrder", "BUILT_AT", "Plant")] += len(self.orders)
        e[("ProductionOrder", "OF_MODEL", "Model")] += len(self.orders)
        e[("CustomerOrder", "FROM_BUILD", "ProductionOrder")] += len(self.customer_orders)
        e[("CustomerOrder", "AT_DEALER", "Dealer")] += len(self.customer_orders)
        e[("CustomerOrder", "FOR_CUSTOMER", "Customer")] += len(self.customer_orders)
        for lot in self.lots.values():
            e[("Lot", "OF_PART", "Part")] += 1
            e[("Lot", "FROM_SUPPLIER", "Supplier")] += 1
            e[("Lot", "AT_PLANT", "Plant")] += 1
        e[("Vehicle", "FROM_BUILD", "ProductionOrder")] += len(self.vehicles)
        e[("Vehicle", "AT_DEALER", "Dealer")] += len(self.vehicles)
        e[("Vehicle", "OWNED_BY", "Customer")] += sum(1 for v in self.vehicles.values() if v["customer_id"])

    def entity_counts(self) -> dict[str, int]:
        return {
            "Plant": len(self.plants),
            "Model": len(self.models),
            "Part": len(self.parts),
            "Supplier": len(self.suppliers),
            "Shipment": len(self.shipments),
            "Lot": len(self.lots),
            "ProductionOrder": len(self.orders),
            "CustomerOrder": len(self.customer_orders),
            "Customer": len(self.customers),
            "Dealer": len(self.dealers),
            "Vehicle": len(self.vehicles),
            "Alias": len(self.aliases),
            "WorkingDay": len(self.calendar),
        }

    def part_name(self, part_id: str) -> str:
        return self.parts.get(part_id, {}).get("name", part_id)

    def plant_name(self, plant_id: str) -> str:
        return self.plants.get(plant_id, {}).get("name", plant_id)

    def supplier_name(self, supplier_id: str | None) -> str:
        if not supplier_id:
            return ""
        return self.suppliers.get(supplier_id, {}).get("name", supplier_id)

    def match_mentions(self, text: str) -> list[tuple[str, str, str]]:
        """Non-overlapping gazetteer hits, longest phrase first. Returns (type, id, phrase)."""
        lower = text.lower()
        occupied = [False] * len(lower)
        found = []
        for phrase, typ, eid in self.aliases:
            start = 0
            while True:
                i = lower.find(phrase, start)
                if i < 0:
                    break
                j = i + len(phrase)
                before = i == 0 or not lower[i - 1].isalnum()
                after = j == len(lower) or not lower[j].isalnum()
                if before and after and not any(occupied[i:j]):
                    for k in range(i, j):
                        occupied[k] = True
                    found.append((typ, eid, text[i:j]))
                start = i + 1
        return found

    def future_orders(self, plant_id: str, predicate) -> list[str]:
        ids = [
            po for po, o in self.orders.items()
            if o["plant_id"] == plant_id and o["idx"] >= 0 and predicate(o)
        ]
        ids.sort(key=lambda po: (self.orders[po]["idx"], po))
        return ids

    def delay_window(self, plant_id: str, part_id: str, old_idx: int, new_idx: int) -> list[str]:
        models = self.part_models[part_id]
        return self.future_orders(
            plant_id,
            lambda o: o["model"] in models and old_idx <= o["idx"] < new_idx,
        )

    def outage_window(self, plant_id: str, start_idx: int, end_idx: int) -> list[str]:
        return self.future_orders(
            plant_id,
            lambda o: start_idx <= o["idx"] <= end_idx,
        )

    def orders_for_cos(self, po_ids: list[str]) -> list[dict]:
        rows = []
        for po in po_ids:
            for cid in self.pos_to_cos.get(po, []):
                rows.append(self.customer_orders[cid])
        return rows

    def vehicles_for_lot(self, lot: dict) -> list[dict]:
        """Lot → production orders of models that use the part → vehicles built in the lot window."""
        part = lot["part_id"]
        plant = lot["plant_id"]
        first, last = lot["first_build_date"], lot["last_build_date"]
        models = self.part_models[part]
        hits = []
        for v in self.vehicles.values():
            if v["plant_id"] != plant:
                continue
            if not (first <= v["build_date"] <= last):
                continue
            po = self.orders.get(v["production_order_id"])
            if po is None or po["model"] not in models:
                continue
            hits.append(v)
        hits.sort(key=lambda v: (v["vin"],))
        return hits

    def cite_delay(self, shipment_id: str, po_ids: list[str]) -> list[dict]:
        ship = self.shipments[shipment_id]
        part = ship["part_id"]
        paths = []
        for po in po_ids:
            model = self.orders[po]["model"]
            cos = self.pos_to_cos.get(po, [])
            if not cos:
                paths.append({
                    "chain": f"{shipment_id} → {part} → {model} (BOM) → {po}",
                    "nodes": [shipment_id, part, model, po],
                })
                continue
            for cid in cos:
                co = self.customer_orders[cid]
                paths.append({
                    "chain": (
                        f"{shipment_id} → {part} → {model} (BOM) → {po} → "
                        f"{cid} → {co['dealer_id']} / {co['customer_id']}"
                    ),
                    "nodes": [shipment_id, part, model, po, cid, co["dealer_id"], co["customer_id"]],
                })
        return paths

    def cite_outage(self, plant_id: str, po_ids: list[str]) -> list[dict]:
        paths = []
        for po in po_ids:
            cos = self.pos_to_cos.get(po, [])
            if not cos:
                paths.append({"chain": f"{plant_id} → {po}", "nodes": [plant_id, po]})
                continue
            for cid in cos:
                co = self.customer_orders[cid]
                paths.append({
                    "chain": f"{plant_id} → {po} → {cid} → {co['dealer_id']} / {co['customer_id']}",
                    "nodes": [plant_id, po, cid, co["dealer_id"], co["customer_id"]],
                })
        return paths

    def cite_quality(self, lot: dict, vehicles: list[dict]) -> list[dict]:
        paths = []
        for v in vehicles:
            who = v["customer_id"] or "unsold"
            paths.append({
                "chain": (
                    f"{lot['lot_id']} → {v['production_order_id']} → {v['vin']} → "
                    f"{v['dealer_id']} / {who}"
                ),
                "nodes": [lot["lot_id"], v["production_order_id"], v["vin"], v["dealer_id"], who],
            })
        return paths

    def blocked(self, plant_id: str, model: str, idx: int, incidents: list[dict]) -> bool:
        """A slot is not feasible if this same event already closed it."""
        for inc in incidents:
            if inc["kind"] == "plant_outage" and inc["plant_id"] == plant_id:
                if inc["start_idx"] <= idx <= inc["end_idx"]:
                    return True
            if inc["kind"] == "supplier_delay" and inc["plant_id"] == plant_id:
                if model in self.part_models[inc["part_id"]] and inc["old_idx"] <= idx < inc["new_idx"]:
                    return True
        return False
