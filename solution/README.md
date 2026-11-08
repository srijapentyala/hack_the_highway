# Wacky Wheels control tower

Hack the Highway submission. The company data and `enterprise_server.py` are unchanged.

## Run

From the package root:

```bash
python3 solution/run.py
python3 solution/control_tower.py
```

Open http://127.0.0.1:8090 . The official log is `runs/run1/action_log.jsonl`. Per-event traces are `runs/run1/traces/`. The ontology export is `runs/run1/ontology.json`. The one-page design card is `solution/design_card.pdf` (PNG and HTML source alongside).

MongoDB Atlas mirrors that finished run. It does not call enterprise tools and does not rewrite the action log.

```bash
MONGODB_URI='mongodb+srv://...' python3 solution/load_atlas.py
MONGODB_URI='mongodb+srv://...' python3 solution/control_tower.py --atlas
```

```bash
python3 solution/run.py --rehearse-only   # policy check, no server
python3 solution/run.py --llm          # Llama 3.2 3B via local Ollama, no API key
```

Ollama must be running (`ollama serve`) with `llama3.2:3b` pulled. If `OPENAI_API_KEY` is set, that key is used instead.

## Model

This run read every event with **Llama 3.2 3B** (`llama3.2:3b`) through Ollama on this Mac. No API key. It agreed with the ontology reader on 12 of 15 events. On E-01, E-03, and E-09 the reader stayed in force, so the 909 tool calls and 0 failures are unchanged. Policy, slots, and tool arguments are code either way.

## Agents

Coordinator, Supply Chain Planner, Quality Sentinel, Dealer & Customer Desk. Specialists return plans. The coordinator is the only component that calls tools, after validation.
