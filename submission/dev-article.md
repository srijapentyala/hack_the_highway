---
title: The model can read the radio. It does not get the keys to the factory.
published: false
tags: ai, python, machinelearning, architecture
canonical_url:
cover_image:
---

Monday, 8 March 2027. Wacky Wheels Co. builds cars without a parts crib. If a shipment is late, the line waits. If a plant goes dark, those builds have to move. If a lot of parts is bad, the cars that already left the factory need a phone call, and the ones still on a dealer lot need to come off sale.

The night shift did not leave a clean ticket. They left fifteen messages. One of them is a morning digest with two incidents in it. Two are rumors. Three have nothing to do with the factory at all. The rest are outages, late trucks, and quality holds, written the way people write: nicknames for plants, "next Friday," a supplier's first name.

We built a control tower that can read that feed and then do the boring, dangerous part correctly. Touch the orders the event actually reaches. Leave the rest of the company where it is.

## One radio, four desks

The tower is one coordinator and three specialists.

The coordinator splits the message. If it is noise, the specialists never stand up. If it is a rumor with no date and no shipment, the coordinator escalates to a person and writes nothing else. If it is real, the coordinator hands each incident to the desk that owns it.

The supply planner walks from a plant, or from a late shipment through the bill of materials, to the production orders in that window. It moves each one to the earliest open slot. It transfers a build to another plant only when the home plant has no day left. The quality sentinel holds the lot, stops sale on unsold vehicles from that lot, and contacts the owners of the ones already sold. The dealer desk sends one notice to each dealer, listing only that dealer's orders, and hands out loaners in the order the handbook already decided: platinum, then gold, then the earlier promise.

Specialists return a plan. The coordinator is the only one who sends it. A gateway checks every argument before the enterprise tool runs. A rejected call stays in the log and is not retried.

## The graph is the authority

The company is a graph, not a prompt. Six plants, twenty parts, eighteen suppliers, 364 shipments, 540 production orders, 3,263 customer orders, 7,000 customers, 50 dealers, 5,348 finished vehicles, and a calendar of working days. Aliases sit on the nodes, so "the Huntsville line" and a plant id can be the same place.

Every real incident has to show its path. A late shipment is Shipment, Part, Model, Production Order, Customer Order, Dealer or Customer. An outage is Plant, Production Order, Customer Order, Dealer or Customer. A bad lot is Lot, Production Order, Vehicle, Dealer or Customer. If the walk does not reach a record, that record does not move.

That rule is what makes a compound morning safe. The digest can contain a San Antonio outage and a late infotainment chip for Princeton. Both get handled. They share one slot board and one loaner pool, so the second incident cannot book a day or a car the first incident already took.

## The model proposes. The binding disposes.

A small local model, Llama 3.2 3B, reads each message. We asked it for a disposition, a kind of incident, and the plant, part, supplier, and date phrases copied out of the text. We did not ask it for an order id, a VIN, or a slot. Temperature stays at zero. There is no API key on the scored path.

Then the same gazetteer and calendar that the rule reader uses try to bind those phrases to exactly one plant, one shipment, or one lot. If the bound incidents match the ontology reader, that agreed reading is what we execute. If they do not match, the ontology stays in force.

On this run the model agreed on 12 of the 15 events. On the other three its reading did not bind to the same incidents, so the reader kept the decision and the tool arguments did not change. The log is 909 calls and 0 failures: 57 reschedules, 8 transfers, 201 dealer notices, 123 loaner assignments, 3 lots held, 98 stop-sales, 320 owner contacts, and 2 escalations. The three noise messages contributed zero of those calls.

This is the split we would keep even with a larger model. A better reader would close the three disagreements. It would still not be allowed to pick the slot.

## What we left alone

Restraint is half the system. A brochure question, a weather note about somewhere we do not build, a price-list update: no tool is called, and escalate is not used either, because those messages are irrelevant rather than unclear. A rumor about seat material with no date, and a floor comment about "something electronic sometime soon," each become one escalate. No order, dealer, customer, or lot is touched on the way.

The control-tower view shows the feed, the path, the handoff between desks, and the audit line for each event. The thing a judge can check is the same thing an operator would want: what arrived, what it touched, and why the rest of the plant was left alone.

## How the weekend was staffed

Cursor was the coding agent. It wrote the desks, the binder, the gateway, and the board with us in the loop. Grok Bot sat beside that as Highway Desk. Its job is a skill called Highway submission desk: read the project description, check that the story still matches the run, and stop. It does not get a tool, and it does not publish. The factory keys stay in the gateway.

The run itself fits on a laptop. The company systems are a local server. The scored file is the action log from that server.

We would next point a stronger reader at the same binder, and keep the rule that a model which cannot bind an incident does not get to invent one.
