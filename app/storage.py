from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models import HistoryEvent, PetProfile, SafetyResult

DB_PATH = Path(__file__).resolve().parents[1] / "petlens.db"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                item_name TEXT NOT NULL,
                species TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                profile_json TEXT NOT NULL
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(history)").fetchall()}
        if "event_json" not in columns:
            conn.execute("ALTER TABLE history ADD COLUMN event_json TEXT")


def save_result(result: SafetyResult, profile: PetProfile) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO history(created_at,item_name,species,risk_level,confidence,result_json,profile_json) VALUES(?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                result.normalized_item,
                profile.species,
                result.risk_level,
                result.confidence,
                result.model_dump_json(),
                profile.model_dump_json(),
            ),
        )


def save_event(
    result: SafetyResult,
    profile: PetProfile,
    *,
    input_text: str = "",
    event_note: str = "",
    question: str = "",
    recognized_item: str = "",
    final_item: str = "",
    user_corrected: bool = False,
    image_attached: bool = False,
    analysis_context: dict | None = None,
) -> HistoryEvent:
    """Persist the first event type while keeping result/profile columns compatible."""
    created_at = datetime.now(timezone.utc).isoformat()
    event = HistoryEvent(
        event_id=f"event:{uuid4().hex}",
        event_type="event",
        event_schema_version=2,
        is_legacy=False,
        created_at=created_at,
        item_name=result.normalized_item,
        species=profile.species,
        risk_level=result.risk_level,
        confidence=result.confidence,
        input_text=input_text,
        event_note=event_note,
        question=question,
        recognized_item=recognized_item,
        final_item=final_item or result.normalized_item,
        user_corrected=user_corrected,
        image_attached=image_attached,
        analysis_context=analysis_context or {},
        result=result,
        profile=profile,
    )
    event_metadata = event.model_dump(exclude={"result", "profile"})
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO history(
                created_at,item_name,species,risk_level,confidence,result_json,profile_json,event_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                created_at,
                result.normalized_item,
                profile.species,
                result.risk_level,
                result.confidence,
                result.model_dump_json(),
                profile.model_dump_json(),
                json.dumps(event_metadata, ensure_ascii=False),
            ),
        )
    return event


def list_history(limit: int = 30) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT created_at,item_name,species,risk_level,confidence FROM history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_history(limit: int = 30) -> list[tuple[SafetyResult, PetProfile]]:
    """Read both current and pre-claims history rows through model compatibility validators."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT result_json,profile_json FROM history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [(SafetyResult.model_validate_json(result), PetProfile.model_validate_json(profile))
            for result, profile in rows]


def load_event_history(limit: int = 30) -> list[HistoryEvent]:
    """Expose legacy and new object-event rows through one event-shaped reader.

    Rows without event metadata are represented as legacy object events. New
    object events keep their event metadata in ``event_json`` while continuing
    to use the original result/profile columns.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id,created_at,item_name,species,risk_level,confidence,result_json,profile_json,event_json
            FROM history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    events: list[HistoryEvent] = []
    for row in rows:
        result = SafetyResult.model_validate_json(row["result_json"])
        profile = PetProfile.model_validate_json(row["profile_json"])
        metadata: dict = {}
        if row["event_json"]:
            try:
                candidate = json.loads(row["event_json"])
                if isinstance(candidate, dict):
                    metadata = candidate
            except (TypeError, json.JSONDecodeError):
                metadata = {}

        if metadata:
            event_data = {
                **metadata,
                "item_name": row["item_name"],
                "species": row["species"],
                "risk_level": row["risk_level"],
                "confidence": row["confidence"],
                "result": result,
                "profile": profile,
            }
        else:
            event_data = {
                "event_id": f"history:{row['id']}",
                "event_type": "object",
                "event_schema_version": 0,
                "is_legacy": True,
                "created_at": row["created_at"],
                "item_name": row["item_name"],
                "species": row["species"],
                "risk_level": row["risk_level"],
                "confidence": row["confidence"],
                "recognized_item": row["item_name"],
                "final_item": row["item_name"],
                "result": result,
                "profile": profile,
            }
        events.append(HistoryEvent.model_validate(event_data))
    return events
