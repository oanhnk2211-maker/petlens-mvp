from app.knowledge import find_local_matches
from app.models import PetProfile
from app.pipeline import evaluate_item


def test_local_match_chocolate_dog():
    rows = find_local_matches("巧克力", "狗")
    assert rows
    assert rows[0]["risk_level"] == "紧急"


def test_fallback_pipeline_without_keys(monkeypatch):
    for key in ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "TAVILY_API_KEY", "OPENAI_COMPATIBLE_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    result = evaluate_item("百合", PetProfile(species="猫"))
    assert result.risk_level == "紧急"
    assert result.scores.poison >= 90
