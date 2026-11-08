#!/usr/bin/env python3
"""Visual board for the Wacky Wheels run. Reads runs/run1/report.json. Does not call tools.

    streamlit run solution/showcase.py --server.port 8501
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "runs" / "run1" / "report.json"

INK = "#f6efe6"
MUTED = "#b7a89a"
COPPER = "#f0b58a"
PAPER = "#0e0c0b"
CARD = "#171412"
COLORS = {
    "Plant outage": "#ff9aaa",
    "Supplier delay": "#f3c56b",
    "Quality hold": "#9ec0ff",
    "Noise": "#b7a89a",
    "Unconfirmed report": "#d7b8ff",
}
AGENTS = {
    "Coordinator": "#f6efe6",
    "Supply Chain Planner": "#f3c56b",
    "Quality Sentinel": "#9ec0ff",
    "Dealer & Customer Desk": "#8fd9cf",
}


def load() -> dict:
    return json.loads(REPORT.read_text())


def tone(categories: list[str]) -> str:
    for name in ("Plant outage", "Supplier delay", "Quality hold", "Noise", "Unconfirmed report"):
        if name in categories:
            return COLORS[name]
    return COPPER


def chart_layout(title: str, height: int = 320) -> dict:
    return dict(
        title=dict(text=title, font=dict(size=14, color=MUTED), x=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, family="Avenir Next, Segoe UI, sans-serif"),
        height=height,
        margin=dict(l=8, r=8, t=42, b=8),
        legend=dict(orientation="h", y=-0.18, font=dict(size=11, color=MUTED)),
        xaxis=dict(showgrid=False, zeroline=False, color=MUTED),
        yaxis=dict(gridcolor="rgba(246,239,230,0.08)", zeroline=False, color=MUTED),
    )


def apply_theme() -> None:
    st.markdown(
        f"""
        <style>
          .stApp {{
            background:
              radial-gradient(900px 380px at 100% -10%, rgba(240,181,138,0.16), transparent 46%),
              linear-gradient(180deg, #14110f 0%, {PAPER} 100%);
            color: {INK};
          }}
          [data-testid="stHeader"] {{ background: transparent; }}
          [data-testid="stToolbar"] {{ display: none; }}
          h1, h2, h3, p, label, span {{ color: {INK}; }}
          .hero-kicker {{
            letter-spacing: 0.18em; text-transform: uppercase; color: {COPPER};
            font-size: 12px; margin: 0;
          }}
          .hero-title {{
            font-family: Didot, "Bodoni 72", Palatino, serif; font-weight: 500;
            font-size: 58px; line-height: 0.95; margin: 4px 0 8px;
          }}
          .card {{
            background: {CARD}; border: 1px solid rgba(246,239,230,0.12);
            border-radius: 16px; padding: 14px 16px; margin-bottom: 10px;
          }}
          .card b {{ display: block; font-size: 28px; font-family: Didot, Palatino, serif; font-weight: 500; }}
          .card span {{ color: {MUTED}; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }}
          .agent {{
            background: {CARD}; border-radius: 16px; padding: 14px 16px;
            border-top: 3px solid var(--tone); min-height: 150px;
          }}
          .agent h3 {{ margin: 0 0 6px; font-size: 18px; }}
          .agent p {{ color: #e7d9cc; font-size: 14px; line-height: 1.4; }}
          .node {{
            display: inline-block; background: #221c18; border-radius: 12px;
            padding: 8px 10px; margin: 4px 4px 4px 0; border: 1px solid rgba(240,181,138,0.35);
            font-size: 13px;
          }}
          .node em {{ display: block; font-style: normal; color: {COPPER}; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def metric_row(pairs: list[tuple[str, str]]) -> None:
    cols = st.columns(len(pairs))
    for col, (value, label) in zip(cols, pairs):
        col.markdown(f'<div class="card"><b>{value}</b><span>{label}</span></div>', unsafe_allow_html=True)


def category_donut(events: list[dict]) -> go.Figure:
    counts: Counter[str] = Counter()
    for ev in events:
        for cat in ev["categories"] or ["Other"]:
            counts[cat] += 1
    fig = go.Figure(go.Pie(
        labels=list(counts),
        values=list(counts.values()),
        hole=0.62,
        marker=dict(colors=[COLORS.get(k, COPPER) for k in counts], line=dict(color=PAPER, width=2)),
        textinfo="value",
        textfont=dict(color=INK, size=14),
        hovertemplate="%{label}<br>%{value} events<extra></extra>",
    ))
    fig.update_layout(**chart_layout("What the morning contained", 340))
    return fig


def tool_bars(events: list[dict]) -> go.Figure:
    counts: Counter[str] = Counter()
    for ev in events:
        for action in ev["actions"]:
            counts[action["tool"]] += 1
    names = [name for name, _ in counts.most_common()]
    values = [counts[name] for name in names]
    fig = go.Figure(go.Bar(
        x=values,
        y=names,
        orientation="h",
        marker=dict(color=COPPER, line=dict(width=0)),
        hovertemplate="%{y}<br>%{x} calls<extra></extra>",
    ))
    fig.update_layout(**chart_layout("Every tool the desks sent", 340))
    fig.update_yaxes(autorange="reversed")
    return fig


def agent_bars(events: list[dict]) -> go.Figure:
    counts: Counter[str] = Counter()
    for ev in events:
        for action in ev["actions"]:
            counts[action["agent"]] += 1
    names = list(AGENTS)
    fig = go.Figure(go.Bar(
        x=names,
        y=[counts[name] for name in names],
        marker=dict(color=[AGENTS[name] for name in names]),
        hovertemplate="%{x}<br>%{y} calls<extra></extra>",
    ))
    fig.update_layout(**chart_layout("Who placed the calls", 300))
    return fig


def day_timeline(events: list[dict]) -> go.Figure:
    fig = go.Figure()
    for cat, color in COLORS.items():
        rows = [ev for ev in events if cat in ev["categories"]]
        if not rows:
            continue
        fig.add_trace(go.Scatter(
            x=[ev["received_at"][11:16] for ev in rows],
            y=[cat] * len(rows),
            mode="markers+text",
            text=[ev["event_id"] for ev in rows],
            textposition="top center",
            textfont=dict(size=11, color=INK),
            marker=dict(
                size=[14 + min(ev["stats"]["tool_calls"], 180) / 12 for ev in rows],
                color=color,
                line=dict(color=PAPER, width=1),
            ),
            name=cat,
            customdata=[ev["event_id"] for ev in rows],
            hovertemplate="%{customdata}<br>%{x}<br>%{y}<extra></extra>",
        ))
    fig.update_layout(**chart_layout("The shift, event by event. Size is the number of calls.", 380))
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    return fig


def plant_chart(event: dict) -> go.Figure | None:
    if not event["moves"]:
        return None
    plants: Counter[str] = Counter(m["to_plant"] for m in event["moves"])
    names = list(plants)
    fig = go.Figure(go.Bar(
        x=names,
        y=[plants[n] for n in names],
        marker=dict(color=COPPER),
        hovertemplate="%{x}<br>%{y} orders land here<extra></extra>",
    ))
    fig.update_layout(**chart_layout("Where the orders landed", 260))
    return fig


def path_html(event: dict) -> str:
    blocks = []
    for path in event["paths"]:
        steps = [s.strip() for s in (path.get("pattern") or "").split("→")]
        nodes = "".join(f'<span class="node"><em>0{i + 1}</em>{step}</span>' for i, step in enumerate(steps))
        blocks.append(f'<div class="card"><span>{path["incident"]}</span><div style="margin-top:8px">{nodes}</div><p style="color:#e7d9cc">{path.get("walk", "")}</p></div>')
    if not blocks:
        return '<div class="card"><span>No graph walk</span><p>This message did not name a shipment, a plant window, or a lot.</p></div>'
    return "".join(blocks)


def main() -> None:
    st.set_page_config(page_title="Wacky Wheels board", page_icon="◎", layout="wide")
    apply_theme()
    if not REPORT.exists():
        st.error(f"No run at {REPORT}. Generate it with solution/run.py first.")
        return
    report = load()
    events = report["events"]
    by_id = {ev["event_id"]: ev for ev in events}
    meta = report["meta"]

    st.markdown(
        '<p class="hero-kicker">Wacky Wheels · Monday 8 March 2027</p>'
        '<div class="hero-title">The shift, on one board</div>'
        f'<p style="color:{MUTED}">{meta["model"]}</p>',
        unsafe_allow_html=True,
    )
    agreed = sum(1 for ev in events if (ev.get("llm") or {}).get("agrees") is True)
    metric_row([
        (str(len(events)), "Events"),
        (str(meta["n_tool_calls"]), "Tool calls"),
        (str(meta["n_failed"]), "Failed"),
        (f"{agreed}/{len(events)}", "Model agreed"),
        (str(sum(1 for ev in events if ev["disposition"] == "noise")), "Noise held"),
        (str(sum(1 for ev in events if ev["disposition"] == "unconfirmed")), "Escalated"),
    ])

    left, right = st.columns(2)
    with left:
        st.plotly_chart(category_donut(events), width="stretch", config={"displayModeBar": False})
    with right:
        st.plotly_chart(tool_bars(events), width="stretch", config={"displayModeBar": False})
    st.plotly_chart(agent_bars(events), width="stretch", config={"displayModeBar": False})

    picked = st.session_state.get("event_id", "E-01")
    chart = day_timeline(events)
    chosen = st.plotly_chart(
        chart,
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key="shift",
        config={"displayModeBar": False},
    )
    points = []
    if isinstance(chosen, dict):
        points = (chosen.get("selection") or {}).get("points") or []
    elif hasattr(chosen, "selection") and chosen.selection is not None:
        points = list(getattr(chosen.selection, "points", []) or [])
    if points:
        custom = points[0].get("customdata") if isinstance(points[0], dict) else getattr(points[0], "customdata", None)
        if custom in by_id:
            picked = custom
            st.session_state["event_id"] = picked

    st.markdown("### Open an event")
    labels = [f"{ev['event_id']}  ·  {', '.join(ev['categories'])}  ·  {ev['stats']['tool_calls']} calls" for ev in events]
    ids = [ev["event_id"] for ev in events]
    choice = st.selectbox("Event", labels, index=ids.index(picked) if picked in ids else 0, label_visibility="collapsed")
    event = by_id[choice.split("  ·")[0]]
    st.session_state["event_id"] = event["event_id"]

    color = tone(event["categories"])
    st.markdown(
        f'<p class="hero-kicker" style="color:{color}">{event["event_id"]} · {(event.get("received_at") or "")[11:16]} · {event.get("source") or ""}</p>'
        f'<div class="hero-title" style="font-size:48px">{", ".join(event["categories"])}</div>',
        unsafe_allow_html=True,
    )
    stats = event["stats"]
    metric_row([
        (str(stats["reschedules"] + stats["transfers"]), "Orders moved"),
        (str(stats["transfers"]), "Transfers"),
        (str(stats["dealer_notices"]), "Dealer notices"),
        (str(stats["loaners"]), "Loaners"),
        (str(stats["lots"]), "Lots held"),
        (str(stats["customers"]), "Owners told"),
        (str(stats["tool_calls"]), "Calls"),
    ])

    story, picture = st.columns([1.15, 0.85])
    with story:
        st.markdown(f'<div class="card"><span>What happened</span><p>{event["summary"]}</p></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card"><span>Why</span><p>{event["reasoning"]}</p></div>', unsafe_allow_html=True)
        llm = event.get("llm") or {}
        note = "Agreed with the ontology reader." if llm.get("agrees") else "Ontology reader kept. The model did not bind to the same incidents."
        if llm.get("used"):
            st.markdown(f'<div class="card"><span>{llm.get("model") or "Model"}</span><p>{note}</p></div>', unsafe_allow_html=True)
    with picture:
        fig = plant_chart(event)
        if fig is not None:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        else:
            st.markdown('<div class="card"><span>No line move</span><p>Nothing was rescheduled. The guardrail is the result.</p></div>', unsafe_allow_html=True)

    st.markdown("### The desks on this event")
    cols = st.columns(4)
    hand = {h["agent"]: h["did"] for h in event["handoffs"]}
    for col, (name, agent_color) in zip(cols, AGENTS.items()):
        calls = sum(1 for a in event["actions"] if a["agent"] == name)
        did = hand.get(name, "Stood down. This event is outside this desk.")
        col.markdown(
            f'<div class="agent" style="--tone:{agent_color}"><h3>{name}</h3><p>{did}</p><p style="color:{MUTED}">{calls} calls</p></div>',
            unsafe_allow_html=True,
        )

    st.markdown("### Graph path")
    st.markdown(path_html(event), unsafe_allow_html=True)

    if event["moves"]:
        st.markdown("### The line")
        st.dataframe(
            [{
                "Order": m["production_order_id"],
                "Model": m["model"],
                "From": f"{m['from_plant']} {m['from_date']}",
                "To": f"{m['to_plant']} {m['to_date']}",
                "Tool": m["tool"],
                "Open before": m["free_before"],
            } for m in event["moves"]],
            width="stretch",
            hide_index=True,
        )
    if event["actions"]:
        st.markdown("### Audit")
        agent_pick = st.pills("Desk", ["All", *AGENTS], default="All") if hasattr(st, "pills") else "All"
        rows = event["actions"]
        if agent_pick and agent_pick != "All":
            rows = [a for a in rows if a["agent"] == agent_pick]
        st.dataframe(
            [{
                "Agent": a["agent"],
                "Tool": a["tool"],
                "Why": a.get("why") or "",
                "Ok": "ok" if a.get("ok", True) else "failed",
            } for a in rows],
            width="stretch",
            hide_index=True,
            height=360,
        )


if __name__ == "__main__":
    main()
