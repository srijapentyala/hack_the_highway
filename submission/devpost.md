# Devpost — paste the description below

Hackathon: TAMU Datathon 26: Casino Royale
Opt into: [MLH] Build Your Hackathon A-Team with SpaceXSI
Built with: Python, Cursor, Grok Bot

## Project name

Hack the Highway

## Tagline

Four agents run a car plant from a messy morning feed, and they refuse to guess.

## Description

Wacky Wheels builds cars with no parts inventory. A late chip, a dark assembly line, or a bad lot has to move the right production orders, warn the right dealers, and leave everyone else alone. The messages use nicknames, relative dates, two incidents in one digest, rumors, and notes that should change nothing.

Hack the Highway is the control tower for that feed. Cursor is the coding agent. Grok Bot is the workflow automation, and its name in this project is Highway Desk. Highway Desk reviews the submission text against evidence pasted into its chat. It does not edit code, call enterprise tools, or publish.

One coordinator and three specialists handle each message. `SupplyChainPlanner.plan`, `QualitySentinel.plan`, and `DealerCustomerDesk.plan` each return a dictionary and do not call the gateway. `Coordinator.handle` stores those dictionaries and builds the event's action list. The only `Gateway.call` sites are `rehearse` and `execute_http` in `solution/run.py`, and both send that action list. The company graph used for those plans is recorded in `runs/run1/report.json`: 6 plants, 540 production orders, 3,263 customer orders, and 5,348 vehicles, among the other entity counts in that file.

`runs/run1/report.json` records the official run as 15 events, 909 tool calls, and 0 failures. `runs/run1/action_log.jsonl` has 909 lines and no failed call. Llama 3.2 3B proposed a reading on all 15 events. The report marks agreement on E-02, E-04, E-05, E-06, E-07, E-08, E-10, E-11, E-12, E-13, E-14, and E-15. On E-01, E-03, and E-09 the report says the ontology reader stayed in force.

The prompt in `solution/tower/llm.py` allows one JSON object: disposition, and incidents with kind, plant, part, supplier, shipment_id, lot_id, and dates. It says not to choose actions and not to invent ids that are not written in the message. Order ids, VINs, and slots are not fields in that object. `Schedule._record` builds `production_order_id` and `new_date` from the graph walk. In `QualitySentinel.plan`, the `quality.hold_lot` args are `{"lot_id": lot["lot_id"]}` after `lot = world.lots[incident["lot_id"]]`. The `dealer.stop_sale` args are `{"dealer_id": dealer, "vins": vins}`, and those VINs are the `vin` fields of in-stock vehicles from `world.vehicles_for_lot`. The `crm.notify_customer` args include `{"customer_id": cid}` for customer ids on sold vehicles from that same list, and they also include `message`. In `DealerCustomerDesk.plan`, the `dealer.notify` args include `{"dealer_id": dealer, "customer_order_ids": ids}` from `notify_groups(customer_orders)`, and they also include `message`. The `crm.assign_loaner` args are `{"customer_order_id": co["customer_order_id"]}` from the ranked customer orders inside that dealer's pool. One `Schedule` is created per event before any incident is planned, so a compound message shares that slot board. Loaners for that event are assigned in one pass from each dealer's pool. E-05, E-06, and E-07 are noise and have empty action lists. E-02 and E-13 each contain one `escalate` and no other tool.

The SpaceXSI opt-in is the checkbox on this form, not a claim that entry is already finished.
