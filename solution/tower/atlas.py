"""MongoDB Atlas mirror of a finished run.

The scored action log stays on disk. Atlas holds the ontology and the fifteen
event traces so the control tower can read them back.
"""
from __future__ import annotations

import os
from typing import Any

RUN_ID = "run1"
DEFAULT_DB = "hack_the_highway"


def uri() -> str:
    return os.environ.get("MONGODB_URI", "").strip()


def db_name() -> str:
    return os.environ.get("MONGODB_DB", DEFAULT_DB).strip() or DEFAULT_DB


def _client(connection: str):
    import certifi
    from pymongo import MongoClient

    return MongoClient(
        connection,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=8000,
    )


def documents_from_report(report: dict) -> dict[str, Any]:
    """Split the local report into the collections Atlas stores."""
    onto = report["ontology"]
    return {
        "run": {"_id": RUN_ID, **report["meta"]},
        "ontology": {
            "_id": RUN_ID,
            "today": onto.get("today"),
            "paths": onto.get("paths") or {},
        },
        "entities": [
            {"_id": row["type"], "type": row["type"], "count": row["count"]}
            for row in onto.get("entities") or []
        ],
        "relations": [
            {
                "_id": f"{row['from']}|{row['edge']}|{row['to']}",
                "from": row["from"],
                "edge": row["edge"],
                "to": row["to"],
                "count": row["count"],
                "meaning": row.get("meaning") or "",
            }
            for row in onto.get("relations") or []
        ],
        "events": [
            {"_id": event["event_id"], **event}
            for event in report.get("events") or []
        ],
    }


def report_from_documents(docs: dict[str, Any]) -> dict:
    """Rebuild the report shape the control tower already renders."""
    run = {k: v for k, v in docs["run"].items() if k != "_id"}
    head = docs["ontology"]
    entities = [{"type": row["type"], "count": row["count"]} for row in docs["entities"]]
    relations = [
        {
            "from": row["from"],
            "edge": row["edge"],
            "to": row["to"],
            "count": row["count"],
            "meaning": row.get("meaning") or "",
        }
        for row in docs["relations"]
    ]
    events = []
    for event in docs["events"]:
        events.append({k: v for k, v in event.items() if k != "_id"})
    return {
        "meta": run,
        "ontology": {
            "today": head.get("today"),
            "entities": entities,
            "relations": relations,
            "paths": head.get("paths") or {},
        },
        "events": events,
    }


def publish(report: dict, connection: str | None = None, name: str | None = None) -> dict[str, int]:
    """Replace the run1 collections. Returns the number of documents written."""
    connection = connection or uri()
    name = name or db_name()
    if not connection:
        raise RuntimeError("MONGODB_URI is not set")
    docs = documents_from_report(report)
    client = _client(connection)
    try:
        client.admin.command("ping")
        database = client[name]
        database.runs.replace_one({"_id": RUN_ID}, docs["run"], upsert=True)
        database.ontology.replace_one({"_id": RUN_ID}, docs["ontology"], upsert=True)
        for collection, rows in (
            ("entities", docs["entities"]),
            ("relations", docs["relations"]),
            ("events", docs["events"]),
        ):
            database[collection].delete_many({})
            if rows:
                database[collection].insert_many(rows)
        database.events.create_index("event_id")
        database.entities.create_index("type")
        return {
            "entities": len(docs["entities"]),
            "relations": len(docs["relations"]),
            "events": len(docs["events"]),
        }
    finally:
        client.close()


def fetch_report(connection: str | None = None, name: str | None = None) -> dict:
    """Read the control-tower report back from Atlas."""
    connection = connection or uri()
    name = name or db_name()
    if not connection:
        raise RuntimeError("MONGODB_URI is not set")
    client = _client(connection)
    try:
        client.admin.command("ping")
        database = client[name]
        run = database.runs.find_one({"_id": RUN_ID})
        head = database.ontology.find_one({"_id": RUN_ID})
        if run is None or head is None:
            raise RuntimeError(f"no run in {name}. Load it with solution/load_atlas.py")
        entities = list(database.entities.find().sort("type", 1))
        relations = list(database.relations.find().sort([("from", 1), ("edge", 1)]))
        events = list(database.events.find().sort("event_id", 1))
        return report_from_documents({
            "run": run,
            "ontology": head,
            "entities": entities,
            "relations": relations,
            "events": events,
        })
    finally:
        client.close()
