from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any, MutableMapping

from pydantic import BaseModel, Field, field_validator


class VisionError(RuntimeError):
    """A safe, user-facing vision recognition error."""


class VisionResult(BaseModel):
    item_name: str
    normalized_name: str
    visible_text: list[str] = Field(default_factory=list)
    candidate_names: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    description: str = ""
    uncertainty: str = ""

    @field_validator("item_name", "normalized_name")
    @classmethod
    def require_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


class VisionProvider(ABC):
    @abstractmethod
    def recognize(self, image_bytes: bytes, media_type: str) -> VisionResult:
        raise NotImplementedError


def image_fingerprint(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def recognize_once(
    provider: VisionProvider,
    image_bytes: bytes,
    media_type: str,
    state: MutableMapping[str, Any],
    *,
    force: bool = False,
) -> VisionResult:
    """Recognize once per image in a mutable session state unless explicitly forced."""
    fingerprint = image_fingerprint(image_bytes)
    cache = state.setdefault("vision_results", {})
    if not force and fingerprint in cache:
        return VisionResult.model_validate(cache[fingerprint])
    result = provider.recognize(image_bytes, media_type)
    cache[fingerprint] = result.model_dump()
    state["active_vision_fingerprint"] = fingerprint
    return result
