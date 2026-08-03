from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import AnalysisResult, PetProfile
from app.pipeline import evaluate_item
from app.providers.mock_text import MockTextProvider
from app.providers.qwen_text import QwenTextProvider
from app.providers.text_base import TextAnalysisError
from app.providers.vision_base import VisionResult


def analysis(**changes):
    value = {
        "item_name": "蒙古包", "overall_risk": "通常低风险", "confidence": 0.72,
        "evidence_level": "general_inference", "item_category": "环境设施",
        "scores": {"food": 0, "toxicity": 5, "toy": 5, "physical_danger": 35, "interest": 30},
        "tags": ["环境设施", "非食品", "注意炉火", "注意绳索"],
        "summary": "蒙古包整体通常不是食品或毒物，应关注具体设施风险。",
        "details": "没有发现明确的直接毒性依据；炉灶、绳索和支架需要分别管理。",
        "exceptions": ["炉灶可能烫伤", "绳索可能缠绕"], "advice": ["隔离使用中的炉灶"],
        "emergency_signs": [], "sources": [],
    }
    value.update(changes)
    return value


def test_unknown_calls_text_model_and_mongolian_yurt_is_not_fixed_warning():
    provider = MockTextProvider(analysis())
    result = evaluate_item("蒙古包", PetProfile(species="狗"), text_provider=provider)
    assert provider.calls == 1
    assert result.item_category == "环境设施"
    assert result.evidence_level == "general_inference"
    assert "禁止宠物接触或食用" not in result.direct_conclusion


def test_exact_local_facts_override_model():
    unsafe = analysis(item_name="巧克力", overall_risk="通常低风险", confidence=0.9,
                      scores={"food": 80, "toxicity": 0, "toy": 20, "physical_danger": 0, "interest": 80},
                      summary="可以吃", details="没有危险")
    result = evaluate_item("巧克力", PetProfile(species="狗"), text_provider=MockTextProvider(unsafe))
    assert result.risk_level == "紧急"
    assert result.scores.poison >= 98
    assert "不要给狗吃" in result.direct_conclusion
    assert result.evidence_level == "verified_local"


def test_fabricated_sources_are_removed():
    fake = analysis(sources=[{"title": "虚构研究", "url": "https://fake.invalid", "snippet": "假的", "source_type": "模型知识"}])
    assert evaluate_item("蒙古包", PetProfile(), text_provider=MockTextProvider(fake)).sources == []


@pytest.mark.parametrize("scores", [
    {"food": -1, "toxicity": 5, "toy": 5, "physical_danger": 35, "interest": 30},
    {"food": 0, "toxicity": 101, "toy": 5, "physical_danger": 35, "interest": 30},
])
def test_score_range_is_validated(scores):
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(analysis(scores=scores))


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_range_is_validated(confidence):
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(analysis(confidence=confidence))


def test_no_api_key_falls_back(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    result = evaluate_item("蒙古包", PetProfile(), text_provider=QwenTextProvider(api_key=""))
    assert result.evidence_level == "insufficient"
    assert "未配置" in result.analysis_error


def test_timeout_falls_back():
    result = evaluate_item("蒙古包", PetProfile(), text_provider=MockTextProvider(TextAnalysisError("文本分析请求超时，已使用本地结果。")))
    assert result.evidence_level == "insufficient"
    assert "超时" in result.analysis_error


def test_invalid_json_is_retried_once(monkeypatch):
    provider = QwenTextProvider(api_key="test")
    responses = iter(["bad", __import__("json").dumps(analysis(), ensure_ascii=False)])
    calls = []
    def request(messages):
        calls.append(messages)
        return next(responses)
    monkeypatch.setattr(provider, "_request", request)
    assert provider.analyze_item("蒙古包", "蒙古包", PetProfile(), []).item_category == "环境设施"
    assert len(calls) == 2


def test_vision_text_fields_enter_same_pipeline():
    provider = MockTextProvider(analysis())
    vision = VisionResult(item_name="蒙古包", normalized_name="蒙古包", confidence=.9,
                          description="白色毡房", visible_text=[], candidate_names=["毡房"])
    result = evaluate_item("蒙古包", PetProfile(), vision_result=vision, text_provider=provider)
    assert result.evidence_level == "general_inference"


def test_qwen_request_options(monkeypatch):
    provider = QwenTextProvider(api_key="test")
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps(analysis())))])
    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    provider.analyze_item("蒙古包", "蒙古包", PetProfile(), [])
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["extra_body"] == {"enable_thinking": False}
