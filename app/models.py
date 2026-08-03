from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


Species = Literal["猫", "狗", "兔子", "鸟", "其他"]
RiskLevel = Literal["紧急", "避免", "谨慎", "通常可用", "信息不足"]
EvidenceLevel = Literal["verified_local", "mixed", "general_inference", "insufficient"]
SourceType = Literal["verified_database", "trusted_web", "model_inference", "vision_observation", "user_input"]


class PetProfile(BaseModel):
    name: str = "我的宠物"
    species: Species = "猫"
    age_years: float | None = Field(default=None, ge=0, le=100)
    weight_kg: float | None = Field(default=None, gt=0, le=500)
    notes: str = ""


class AttributeScores(BaseModel):
    food: int = Field(ge=0, le=100)
    poison: int = Field(ge=0, le=100)
    toy: int = Field(ge=0, le=100)
    hazard: int = Field(ge=0, le=100)
    interest: int = Field(ge=0, le=100)


class EvidenceSource(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source_type: Literal["本地知识库", "网络检索", "模型知识"] = "网络检索"


class Claim(BaseModel):
    claim_id: str
    text: str
    claim_type: str
    confidence: float = Field(ge=0, le=1)
    severity: str
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    evidence_id: str
    source_type: SourceType
    organization: str = ""
    title: str = ""
    url: str = ""
    model: str = ""
    retrieved_at: str = ""
    supports: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_source_contract(self):
        if self.url and self.source_type != "trusted_web":
            raise ValueError("只有 trusted_web 证据可以包含外部 URL")
        if self.source_type == "model_inference" and (self.organization or self.url):
            raise ValueError("模型推断不得声明外部机构或 URL")
        return self


def _legacy_claims(data: dict) -> dict:
    """Upgrade old result dictionaries without pretending they have web evidence."""
    if data.get("claims") or data.get("evidence"):
        return data
    texts = [data.get("summary") or data.get("direct_conclusion", ""), data.get("details") or data.get("detailed_explanation", "")]
    texts.extend(data.get("exceptions") or [])
    texts = [str(text).strip() for text in texts if str(text).strip()]
    if not texts:
        return data
    evidence_id = "AI:legacy:unknown:1"
    data["evidence"] = [EvidenceRef(
        evidence_id=evidence_id, source_type="model_inference", title="旧结果兼容推断",
        model="unknown", supports=[f"LEGACY:{i}" for i in range(1, len(texts) + 1)],
    ).model_dump()]
    data["claims"] = [Claim(
        claim_id=f"LEGACY:{i}", text=text, claim_type="legacy", confidence=min(float(data.get("confidence", 0)) / (100 if float(data.get("confidence", 0)) > 1 else 1), 1),
        severity=str(data.get("risk_level") or data.get("overall_risk") or "信息不足"), evidence_ids=[evidence_id],
    ).model_dump() for i, text in enumerate(texts, 1)]
    return data


def _validate_evidence_graph(claims: list[Claim], evidence: list[EvidenceRef]) -> None:
    ids = [item.evidence_id for item in evidence]
    if len(ids) != len(set(ids)):
        raise ValueError("evidence_id 必须唯一")
    known = set(ids)
    missing = {eid for claim in claims for eid in claim.evidence_ids if eid not in known}
    if missing:
        raise ValueError(f"Claim 引用了不存在的 evidence_id: {sorted(missing)}")


class AnalysisScores(BaseModel):
    food: int = Field(ge=0, le=100)
    toxicity: int = Field(ge=0, le=100)
    toy: int = Field(ge=0, le=100)
    physical_danger: int = Field(ge=0, le=100)
    interest: int = Field(ge=0, le=100)


class AnalysisResult(BaseModel):
    item_name: str
    overall_risk: str
    confidence: float = Field(ge=0, le=1)
    evidence_level: EvidenceLevel
    item_category: str
    scores: AnalysisScores
    tags: list[str] = Field(default_factory=list)
    summary: str
    quick_summary: str = ""
    details: str
    exceptions: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    emergency_signs: list[str] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy(cls, value):
        if isinstance(value, dict):
            value = _legacy_claims(dict(value))
            value.setdefault("quick_summary", value.get("summary", ""))
        return value

    @model_validator(mode="after")
    def validate_graph(self):
        _validate_evidence_graph(self.claims, self.evidence)
        return self


class SafetyResult(BaseModel):
    item_name: str
    normalized_item: str
    species: Species
    risk_level: RiskLevel
    confidence: int = Field(ge=0, le=100)
    evidence_level: EvidenceLevel = "insufficient"
    item_category: str = "其他"
    scores: AttributeScores
    tags: list[str] = Field(default_factory=list)
    direct_conclusion: str
    quick_summary: str = ""
    detailed_explanation: str
    exceptions: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    emergency_signs: list[str] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    disclaimer: str = "结果用于风险筛查，不能替代兽医诊断；若已误食或出现异常，应立即联系兽医。"
    analysis_error: str = ""
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy(cls, value):
        if isinstance(value, dict):
            value = _legacy_claims(dict(value))
            value.setdefault("quick_summary", value.get("direct_conclusion", ""))
        return value

    @model_validator(mode="after")
    def validate_graph(self):
        _validate_evidence_graph(self.claims, self.evidence)
        return self
