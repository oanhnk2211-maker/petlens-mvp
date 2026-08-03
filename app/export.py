from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

_SECRET_KEYS = {"api_key", "apikey", "authorization", "authorization_header"}
_DATA_URL = re.compile(r"^data:image/[^;]+;base64,", re.IGNORECASE)


def sanitize_export(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: sanitize_export(item) for key, item in value.items()
                if key.lower() not in _SECRET_KEYS and "api_key" not in key.lower()}
    if isinstance(value, list):
        return [sanitize_export(item) for item in value]
    if isinstance(value, str) and (_DATA_URL.match(value) or value.lower().startswith("bearer ")):
        return "[已移除敏感内容]"
    return value


def export_json(value: Any) -> str:
    return json.dumps(sanitize_export(value), ensure_ascii=False, indent=2)
