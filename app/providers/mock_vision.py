from __future__ import annotations

from app.providers.vision_base import VisionProvider, VisionResult


class MockVisionProvider(VisionProvider):
    """Explicit test double; it is never selected automatically in the app."""

    def __init__(self, result: VisionResult):
        self.result = result
        self.calls = 0

    def recognize(self, image_bytes: bytes, media_type: str) -> VisionResult:
        self.calls += 1
        return self.result
