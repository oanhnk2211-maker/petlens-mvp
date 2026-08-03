from __future__ import annotations

from app.knowledge import find_local_matches
import hashlib
import uuid

from app.models import AnalysisResult, AttributeScores, Claim, EvidenceRef, EvidenceSource, PetProfile, RiskLevel, SafetyResult
from app.providers.qwen_text import QwenTextProvider
from app.providers.text_base import TextAnalysisError, TextProvider
from app.providers.vision_base import VisionResult


def _item_id(row: dict) -> str:
    value = f"{row.get('species', '')}:{row.get('item', '')}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:12]


def _valid_image_hash(image_hash: str | None) -> str | None:
    """Return a usable image fingerprint, excluding placeholder values."""
    if image_hash is None:
        return None
    value = image_hash.strip()
    return value if value and value.lower() != "unknown" else None


def _claims_for_result(result: SafetyResult, *, row: dict | None = None, model: str = "unknown",
                       request_id: str = "unknown", vision_result: VisionResult | None = None,
                       image_hash: str | None = None) -> SafetyResult:
    """Build IDs and the evidence graph in application code, never from model output."""
    result.claims = []
    result.evidence = []
    statements = [("conclusion", result.direct_conclusion)]
    if result.detailed_explanation:
        statements.append(("detail", result.detailed_explanation))
    statements.extend(("exception", value) for value in result.exceptions)
    if row:
        prefix = f"DB:{_item_id(row)}"
        source = (row.get("sources") or [{}])[0]
        for number, (claim_type, text) in enumerate(statements, 1):
            claim_id, evidence_id = f"CLAIM:{prefix}:{number}", f"{prefix}:{number}"
            result.claims.append(Claim(claim_id=claim_id, text=text, claim_type=claim_type,
                                       confidence=result.confidence / 100, severity=result.risk_level,
                                       evidence_ids=[evidence_id]))
            result.evidence.append(EvidenceRef(
                evidence_id=evidence_id, source_type="verified_database", organization="PetLens",
                title=source.get("title", "PetLens 本地条目"), supports=[claim_id],
            ))
    else:
        safe_model = model.replace(":", "_") or "unknown"
        prefix = f"AI:{safe_model}:{request_id}"
        for number, (claim_type, text) in enumerate(statements, 1):
            claim_id, evidence_id = f"CLAIM:{prefix}:{number}", f"{prefix}:{number}"
            result.claims.append(Claim(claim_id=claim_id, text=text, claim_type=claim_type,
                                       confidence=result.confidence / 100, severity=result.risk_level,
                                       evidence_ids=[evidence_id]))
            result.evidence.append(EvidenceRef(
                evidence_id=evidence_id, source_type="model_inference", title="模型一般性推断",
                model=safe_model, supports=[claim_id],
            ))
    valid_image_hash = _valid_image_hash(image_hash)
    if vision_result and valid_image_hash:
        number = 1
        evidence_id = f"VISION:{valid_image_hash}:{number}"
        claim_id = f"CLAIM:{evidence_id}"
        observation = vision_result.description or f"图片识别为：{vision_result.item_name}"
        result.claims.append(Claim(claim_id=claim_id, text=observation, claim_type="visual_observation",
                                   confidence=vision_result.confidence, severity="不适用",
                                   evidence_ids=[evidence_id]))
        result.evidence.append(EvidenceRef(evidence_id=evidence_id, source_type="vision_observation",
                                           title="图片识别观察", model="vision", supports=[claim_id]))
    result.quick_summary = result.quick_summary or result.direct_conclusion
    return SafetyResult.model_validate(result.model_dump())


def _is_exact(item: str, row: dict) -> bool:
    query = item.strip().lower()
    return any(query == name.strip().lower() for name in [row["item"], *row.get("aliases", [])])


def _local_fallback(item: str, profile: PetProfile, matches: list[dict], error: str = "",
                    vision_result: VisionResult | None = None, image_hash: str | None = None) -> SafetyResult:
    if matches:
        row = matches[0]
        result = SafetyResult(
            item_name=item, normalized_item=row["item"], species=profile.species,
            risk_level=row["risk_level"], confidence=row.get("confidence", 85),
            evidence_level="verified_local" if _is_exact(item, row) else "mixed",
            item_category="本地知识条目", scores=AttributeScores(**row["scores"]),
            tags=row.get("tags", []), direct_conclusion=row["direct_conclusion"],
            detailed_explanation=row["detailed_explanation"], exceptions=row.get("exceptions", []),
            recommended_actions=row.get("recommended_actions", []), emergency_signs=row.get("emergency_signs", []),
            sources=[EvidenceSource(**s) for s in row.get("sources", [])], analysis_error=error,
        )
        return _claims_for_result(result, row=row, vision_result=vision_result, image_hash=image_hash)
    result = SafetyResult(
        item_name=item, normalized_item=item, species=profile.species, risk_level="信息不足", confidence=20,
        evidence_level="insufficient", item_category="其他",
        scores=AttributeScores(food=10, poison=20, toy=10, hazard=25, interest=25), tags=["信息不足", "待核实"],
        direct_conclusion="现有名称或信息不足，暂时无法做出可靠判断。",
        detailed_explanation="请补充更准确的名称、成分、材质、尺寸或包装文字后再试。",
        exceptions=["同名物品的成分和形态可能不同。"],
        recommended_actions=["确认物品名称及组成；若已经误食或出现异常，请联系兽医。"],
        emergency_signs=[], sources=[], analysis_error=error,
    )
    return _claims_for_result(result, model="fallback", request_id=str(uuid.uuid4()),
                              vision_result=vision_result, image_hash=image_hash)


def _risk_level(value: str) -> RiskLevel:
    if value in {"紧急", "避免", "谨慎", "通常可用", "信息不足"}:
        return value  # type: ignore[return-value]
    if "紧急" in value or "极高" in value:
        return "紧急"
    if "高风险" in value or "避免" in value:
        return "避免"
    if "不足" in value:
        return "信息不足"
    if "低风险" in value or "通常" in value:
        return "通常可用"
    return "谨慎"


def _allowed_sources(result: AnalysisResult, matches: list[dict]) -> list[EvidenceSource]:
    allowed = {(s.get("title", ""), s.get("url", ""), s.get("snippet", ""))
               for row in matches for s in row.get("sources", [])}
    return [s for s in result.sources if (s.title, s.url, s.snippet) in allowed and s.source_type == "本地知识库"]


def _from_model(item: str, profile: PetProfile, analysis: AnalysisResult, matches: list[dict], *,
                model: str, request_id: str, vision_result: VisionResult | None,
                image_hash: str | None) -> SafetyResult:
    exact = bool(matches and _is_exact(item, matches[0]))
    evidence = "verified_local" if exact else ("mixed" if matches else analysis.evidence_level)
    if not matches and evidence not in {"general_inference", "insufficient"}:
        evidence = "general_inference"
    scores = AttributeScores(food=analysis.scores.food, poison=analysis.scores.toxicity,
                             toy=analysis.scores.toy, hazard=analysis.scores.physical_danger,
                             interest=analysis.scores.interest)
    result = SafetyResult(
        item_name=item, normalized_item=analysis.item_name, species=profile.species,
        risk_level=_risk_level(analysis.overall_risk), confidence=round(analysis.confidence * 100),
        evidence_level=evidence, item_category=analysis.item_category, scores=scores,
        tags=analysis.tags, direct_conclusion=analysis.summary, quick_summary=analysis.quick_summary,
        detailed_explanation=analysis.details,
        exceptions=analysis.exceptions, recommended_actions=analysis.advice,
        emergency_signs=analysis.emergency_signs, sources=_allowed_sources(analysis, matches),
    )
    if exact:
        row = matches[0]
        # Hard facts and urgent guidance are never weakened by generated prose.
        result.risk_level = row["risk_level"]
        result.confidence = max(result.confidence, row.get("confidence", 85))
        result.scores.poison = max(result.scores.poison, row["scores"]["poison"])
        result.scores.hazard = max(result.scores.hazard, row["scores"]["hazard"])
        result.direct_conclusion = row["direct_conclusion"]
        result.detailed_explanation = row["detailed_explanation"] + ("\n\n结合宠物画像：" + analysis.details if analysis.details else "")
        result.exceptions = list(dict.fromkeys(row.get("exceptions", []) + result.exceptions))
        result.recommended_actions = list(dict.fromkeys(row.get("recommended_actions", []) + result.recommended_actions))
        result.emergency_signs = list(dict.fromkeys(row.get("emergency_signs", []) + result.emergency_signs))
        result.sources = [EvidenceSource(**s) for s in row.get("sources", [])]
    return _claims_for_result(result, row=matches[0] if exact else None, model=model,
                              request_id=request_id, vision_result=vision_result, image_hash=image_hash)


def evaluate_item(item: str, profile: PetProfile, *, vision_result: VisionResult | None = None,
                  text_provider: TextProvider | None = None, image_hash: str | None = None) -> SafetyResult:
    matches = find_local_matches(item, profile.species)
    provider = text_provider or QwenTextProvider()
    normalized = vision_result.normalized_name if vision_result else (matches[0]["item"] if matches else item)
    request_id = str(uuid.uuid4())
    model = str(getattr(provider, "model", provider.__class__.__name__))
    try:
        analysis = provider.analyze_item(item, normalized, profile, matches, vision_result)
        return _from_model(item, profile, analysis, matches, model=model, request_id=request_id,
                           vision_result=vision_result, image_hash=image_hash)
    except TextAnalysisError as exc:
        return _local_fallback(item, profile, matches, str(exc), vision_result, image_hash)
    except Exception:
        return _local_fallback(item, profile, matches, "文本分析失败，已使用本地结果。", vision_result, image_hash)
