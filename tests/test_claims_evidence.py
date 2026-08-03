import json

import pytest
from pydantic import ValidationError

from app.export import export_json
from app.models import AnalysisResult, EvidenceRef, PetProfile, SafetyResult
from app.pipeline import evaluate_item
from app.providers.mock_text import MockTextProvider
from app.providers.vision_base import VisionResult
from app import storage


def old_analysis(**changes):
    value = {
        "item_name": "纸箱", "overall_risk": "通常低风险", "confidence": .7,
        "evidence_level": "general_inference", "item_category": "物品",
        "scores": {"food": 0, "toxicity": 0, "toy": 30, "physical_danger": 20, "interest": 60},
        "tags": ["纸箱"], "summary": "通常可接触", "details": "留意胶带。",
        "exceptions": [], "advice": ["移除胶带"], "emergency_signs": [], "sources": [],
    }
    value.update(changes)
    return value


def old_safety():
    return {
        "item_name": "纸箱", "normalized_item": "纸箱", "species": "猫", "risk_level": "谨慎",
        "confidence": 70, "scores": {"food": 0, "poison": 0, "toy": 30, "hazard": 20, "interest": 60},
        "direct_conclusion": "留意胶带", "detailed_explanation": "旧详情",
    }


def test_missing_evidence_reference_fails():
    value = old_analysis(claims=[{"claim_id": "c1", "text": "x", "claim_type": "fact",
                                  "confidence": .5, "severity": "谨慎", "evidence_ids": ["missing"]}], evidence=[])
    with pytest.raises(ValidationError, match="不存在"):
        AnalysisResult.model_validate(value)


def test_duplicate_evidence_id_fails():
    evidence = {"evidence_id": "e1", "source_type": "user_input", "supports": []}
    with pytest.raises(ValidationError, match="必须唯一"):
        AnalysisResult.model_validate(old_analysis(claims=[], evidence=[evidence, evidence]))


def test_model_inference_rejects_url():
    with pytest.raises(ValidationError):
        EvidenceRef(evidence_id="e", source_type="model_inference", url="https://example.com")


def test_trusted_web_accepts_url():
    item = EvidenceRef(evidence_id="e", source_type="trusted_web", url="https://example.com")
    assert item.url == "https://example.com"


def test_database_hit_has_deterministic_verified_evidence():
    result = evaluate_item("巧克力", PetProfile(species="狗"),
                           text_provider=MockTextProvider(old_analysis(item_name="巧克力")))
    assert result.evidence[0].source_type == "verified_database"
    assert result.evidence[0].evidence_id.startswith("DB:")


def test_model_inference_has_application_generated_evidence():
    result = evaluate_item("纸箱", PetProfile(species="猫"), text_provider=MockTextProvider(old_analysis()))
    assert result.evidence[0].source_type == "model_inference"
    assert result.evidence[0].evidence_id.startswith("AI:")


def test_vision_observation_is_not_safety_fact_source():
    vision = VisionResult(item_name="纸箱", normalized_name="纸箱", confidence=.8, description="棕色纸箱")
    result = evaluate_item("纸箱", PetProfile(), vision_result=vision,
                           text_provider=MockTextProvider(old_analysis()), image_hash="abc")
    observation = next(c for c in result.claims if c.claim_type == "visual_observation")
    assert observation.severity == "不适用"
    assert observation.evidence_ids == ["VISION:abc:1"]
    assert all(next(e for e in result.evidence if e.evidence_id == eid).source_type == "vision_observation"
               for eid in observation.evidence_ids)


def test_text_query_without_image_hash_has_no_vision_evidence():
    result = evaluate_item("纸箱", PetProfile(), text_provider=MockTextProvider(old_analysis()))
    assert all(e.source_type != "vision_observation" for e in result.evidence)


@pytest.mark.parametrize("image_hash", [None, "", "unknown"])
def test_vision_result_without_valid_image_hash_has_no_fake_vision_evidence(image_hash):
    vision = VisionResult(item_name="纸箱", normalized_name="纸箱", confidence=.8, description="棕色纸箱")
    result = evaluate_item("纸箱", PetProfile(), vision_result=vision,
                           text_provider=MockTextProvider(old_analysis()), image_hash=image_hash)
    assert result.direct_conclusion == "通常可接触"
    assert all(e.source_type != "vision_observation" for e in result.evidence)
    assert all(c.claim_type != "visual_observation" for c in result.claims)


def test_old_result_auto_upgrades():
    result = SafetyResult.model_validate(old_safety())
    assert result.quick_summary == "留意胶带"
    assert result.claims and result.evidence[0].source_type == "model_inference"


def test_history_reads_new_and_old_structures(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "history.db")
    storage.init_db()
    old = old_safety()
    import sqlite3
    with sqlite3.connect(storage.DB_PATH) as conn:
        conn.execute("INSERT INTO history(created_at,item_name,species,risk_level,confidence,result_json,profile_json) VALUES(?,?,?,?,?,?,?)",
                     ("now", "纸箱", "猫", "谨慎", 70, json.dumps(old, ensure_ascii=False), PetProfile().model_dump_json()))
    current = SafetyResult.model_validate(old)
    storage.save_result(current, PetProfile())
    rows = storage.load_history()
    assert len(rows) == 2 and all(row[0].claims for row in rows)


def test_json_export_removes_secrets_and_base64():
    exported = export_json({"api_key": "secret", "Authorization": "Bearer token",
                            "image": "data:image/png;base64,AAAA", "result": old_safety()})
    assert "secret" not in exported and "Bearer token" not in exported and "AAAA" not in exported
