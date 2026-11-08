# Design card — How the tower decides

**Monday 8 March 2027.** One fresh world per event. **Run** `runs/run1`: 15 events, 909 tool calls, 0 failures. **Model** Llama 3.2 3B (`llama3.2:3b`) on this Mac, no API key. It agreed on 12 of 15 readings.

## Architecture

A message crosses six gates. One ontology. Inside an event, one slot board and one loaner pool.

1. **The wire.** One message. It may hold two incidents, a rumor, or nothing.
2. **Llama reads.** The model proposes the kind, the names, and the date phrases.
3. **The graph binds.** Aliases, the calendar, and exactly one shipment or lot.
4. **Coordinator.** Dispatch the desks, stand down for noise, or escalate.
5. **Specialists.** They walk the ontology and return a plan, not a tool call.
6. **The gateway.** Every argument is checked. Then the enterprise tools run.

| Agent | Job | Tools |
|---|---|---|
| Coordinator | Splits the message. The only sender. | `escalate` |
| Supply Chain Planner | Earliest open slot. Transfer only when the home plant is full. | `mes.reschedule`, `mes.transfer` |
| Quality Sentinel | Hold the lot. Stop the unsold. Call the owners. | `quality.hold_lot`, `dealer.stop_sale`, `crm.notify_customer` |
| Dealer & Customer Desk | One notice per dealer. Platinum, then Gold, then earlier promise, then lower order id. | `dealer.notify`, `crm.loaner_availability`, `crm.assign_loaner` |

Cited paths: Shipment → Part → Model → ProductionOrder → CustomerOrder → Dealer/Customer. Plant → ProductionOrder → CustomerOrder → Dealer/Customer. Lot → ProductionOrder → Vehicle → Dealer/Customer.

## Language model versus code

Llama proposes the incident. It agreed on E-02, E-04, E-05, E-06, E-07, E-08, E-10, E-11, E-12, E-13, E-14, and E-15. On E-01, E-03, and E-09 the proposal did not bind, so the ontology reader stayed in force and the tool arguments did not change. The model never chooses an order, a VIN, or a slot.

Code owns policy, the calendar, capacity, loaner priority, and every tool argument. Same-plant days start at the new ETA or the morning after the outage. A transfer is the earliest open day from today. Tied plants follow the handbook order.

## Guardrails

- **Noise.** No call at all.
- **Rumor.** `escalate` only. No order, dealer, or customer is touched.
- **Check, then send.** A rejected call is kept in the log and not retried. The loaner response caps assignments.
- **One board.** A compound event shares slots and loaners, so nothing is booked twice. One `dealer.notify` per dealer, listing only that dealer's orders. Standard customers get no loaner.

## Evaluation

`solution/run.py` replays the plan on a private `Enterprise` before the server starts. It checks locations, capacity, notices, loaners, held lots, stopped VINs, owner contacts, escalation, and that unaffected orders did not move. The scored file is `runs/run1/action_log.jsonl`.

## What I would improve

A larger local model would close E-01, E-03, and E-09 without being allowed to pick a slot. The handbook should publish the plant tie-break so every team lands the same transfer.
