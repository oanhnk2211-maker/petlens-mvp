from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import PetProfile, SafetyResult

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
