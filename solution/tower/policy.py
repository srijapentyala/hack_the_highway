"""Capacity, priority, and the handbook's move rules. Specialists call this; the model does not."""
from __future__ import annotations

from collections import defaultdict

from .world import LAST_IDX, LOANER_TIERS, TIER_RANK, idx_to_date, iso


class Schedule:
    """Live slot board for one event. Starts as a copy of the future production plan."""

    def __init__(self, world):
        self.world = world
        self.slots: dict[tuple[str, int], set[str]] = defaultdict(set)
        self.loc: dict[str, tuple[str, int]] = {}
        for po, o in world.orders.items():
            if o["idx"] >= 0:
                self.loc[po] = (o["plant_id"], o["idx"])
                self.slots[(o["plant_id"], o["idx"])].add(po)

    def free(self, plant: str, idx: int) -> int:
        return self.world.plants[plant]["slots"] - len(self.slots[(plant, idx)])

    def place(self, po_ids: list[str], ready_idx: int, incidents: list[dict], why_prefix: str) -> list[dict]:
        """Earliest feasible slot on or after ready_idx.

        Same plant first, on or after ready_idx. A transfer is used only when that
        plant has no free slot left in the window. The other plant was not disrupted,
        so the destination is the earliest open day anywhere in the planning window.
        """
        moves = []
        ordered = sorted(po_ids, key=lambda po: (self.world.orders[po]["idx"], po))
        for po in ordered:
            if po not in self.loc:
                continue
            plant, cur_idx = self.loc[po]
            model = self.world.orders[po]["model"]
            choice = self._same_plant(plant, model, ready_idx, incidents)
            if choice is not None:
                day, free_before = choice
                self._commit(po, plant, day)
                moves.append(self._record(
                    po, model, plant, cur_idx, plant, day, "mes.reschedule", free_before,
                    f"{why_prefix} Earliest same-plant day on or after {iso(idx_to_date(ready_idx))} "
                    f"with a free slot ({free_before} open of {self.world.plants[plant]['slots']}).",
                ))
                continue
            transferred = self._transfer(plant, model, incidents)
            if transferred is None:
                raise RuntimeError(f"no feasible slot for {po}")
            dest, day, free_before = transferred
            self._commit(po, dest, day)
            moves.append(self._record(
                po, model, plant, cur_idx, dest, day, "mes.transfer", free_before,
                f"{why_prefix} No free slot remains at {plant} on or after {iso(idx_to_date(ready_idx))}. "
                f"Transferred to {dest} on {iso(idx_to_date(day))}, the earliest open day in the planning "
                f"window at a plant that builds {model}. Tied plants follow the handbook order.",
            ))
        return moves

    def _same_plant(self, plant, model, ready_idx, incidents):
        for day in range(max(ready_idx, 0), LAST_IDX + 1):
            if self.world.blocked(plant, model, day, incidents):
                continue
            free = self.free(plant, day)
            if free > 0:
                return day, free
        return None

    def _transfer(self, plant, model, incidents):
        # Handbook: once the home plant has no feasible slot, "any day" at a plant
        # that builds the model. That plant is outside the disruption, so the search
        # starts at today (index 0), not at the restart date.
        for day in range(0, LAST_IDX + 1):
            for dest in self.world.plant_order:
                if dest == plant or model not in self.world.plants[dest]["models"]:
                    continue
                if self.world.blocked(dest, model, day, incidents):
                    continue
                free = self.free(dest, day)
                if free > 0:
                    return dest, day, free
        return None

    def _commit(self, po, plant, day):
        old = self.loc[po]
        self.slots[old].discard(po)
        self.slots[(plant, day)].add(po)
        self.loc[po] = (plant, day)

    def _record(self, po, model, from_plant, from_idx, to_plant, to_idx, tool, free_before, why):
        args = {"production_order_id": po, "new_date": iso(idx_to_date(to_idx))}
        if tool == "mes.transfer":
            args["to_plant_id"] = to_plant
        return {
            "production_order_id": po,
            "model": model,
            "from_plant": from_plant,
            "from_date": iso(idx_to_date(from_idx)),
            "to_plant": to_plant,
            "to_date": iso(idx_to_date(to_idx)),
            "tool": tool,
            "args": args,
            "free_before": free_before,
            "why": why,
        }


def loaner_ranking(world, customer_orders: list[dict]) -> dict[str, list[dict]]:
    """Platinum before Gold, then earlier promised date, then lower customer-order id. Per dealer."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for co in customer_orders:
        tier = world.customers[co["customer_id"]]["tier"]
        if tier not in LOANER_TIERS:
            continue
        grouped[co["dealer_id"]].append(co)
    for dealer, rows in grouped.items():
        rows.sort(key=lambda co: (
            TIER_RANK[world.customers[co["customer_id"]]["tier"]],
            co["promised_date"],
            co["customer_order_id"],
        ))
    return grouped


def notify_groups(customer_orders: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for co in customer_orders:
        cid = co["customer_order_id"]
        if cid not in grouped[co["dealer_id"]]:
            grouped[co["dealer_id"]].append(cid)
    for dealer in grouped:
        grouped[dealer].sort()
    return grouped
