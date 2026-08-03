from __future__ import annotations

from app.models import AnalysisResult, PetProfile
from app.providers.text_base import TextProvider
from app.providers.vision_base import VisionResult


class MockTextProvider(TextProvider):
    def __init__(self, result: AnalysisResult | dict | Exception):
        self.result = result
        self.calls = 0

    def analyze_item(self, item_name: str, normalized_name: str, pet_profile: PetProfile,
                     local_matches: list[dict], vision_result: VisionResult | None = None) -> AnalysisResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return AnalysisResult.model_validate(self.result)
