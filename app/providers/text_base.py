from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import AnalysisResult, PetProfile
from app.providers.vision_base import VisionResult


class TextAnalysisError(RuntimeError):
    """Safe error suitable for display to the user."""


class TextProvider(ABC):
    @abstractmethod
    def analyze_item(
        self,
        item_name: str,
        normalized_name: str,
        pet_profile: PetProfile,
        local_matches: list[dict],
        vision_result: VisionResult | None = None,
    ) -> AnalysisResult:
        raise NotImplementedError
