from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "items.json"


def load_items() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_local_matches(item: str, species: str, limit: int = 3) -> list[dict]:
    candidates: list[tuple[float, dict]] = []
    query = item.lower().strip()
    for record in load_items():
        if record["species"] != species:
            continue
        aliases = [record["item"], *record.get("aliases", [])]
        exact = any(query == alias.lower() for alias in aliases)
        contains = any(query in alias.lower() or alias.lower() in query for alias in aliases)
        score = max(_similarity(query, alias) for alias in aliases)
        if exact:
            score += 1.0
        elif contains:
            score += 0.4
        if score >= 0.55:
            candidates.append((score, record))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [record for _, record in candidates[:limit]]
