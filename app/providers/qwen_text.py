from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import ValidationError

from app.models import AnalysisResult, PetProfile
from app.providers.text_base import TextAnalysisError, TextProvider
from app.providers.vision_base import VisionResult

logger = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-plus"

SYSTEM_PROMPT = """你是 PetLens 的宠物物品风险分析模块。输出必须是 JSON，不要 Markdown。
你判断的是物品对指定宠物的意义，不是判断物品是否适合人类。分别判断食品价值、毒性、玩具价值、物理危险和宠物兴趣；多个属性可以同时成立。
本地知识库是优先事实来源：不得降低或否认其中明确的毒性、危险性和急救信息；相似物品不得当作完全相同物品。明确区分数据库事实与一般推断。
不得伪造来源、机构、网址、论文或研究；sources 只能逐字使用输入中的本地来源，没有本地来源必须为空。
不确定时降低 confidence 并解释不确定点。食品、药品、植物等未知高风险对象应更谨慎。
普通家具、建筑和环境设施应区分物品整体与炉火、绳索、尖锐件、松散小件等具体风险，不要机械输出“禁止宠物接触或食用”。没有依据时说“没有发现明确的直接毒性依据”，不能说“绝对安全”。只有名称含糊到无法判断具体是什么时才使用 insufficient。
返回 JSON 字段：item_name, overall_risk, confidence(0到1), evidence_level(verified_local/mixed/general_inference/insufficient), item_category, scores{food,toxicity,toy,physical_danger,interest}(均0到100), tags, summary, details, exceptions, advice, emergency_signs, sources。"""


def parse_analysis_result(text: str) -> AnalysisResult:
    decoder = json.JSONDecoder()
    candidates = [text.strip(), *[text[i:] for i, c in enumerate(text) if c == "{"]]
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate.lstrip())
            return AnalysisResult.model_validate(value)
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
            continue
    raise TextAnalysisError("文本模型返回格式错误，已使用本地结果。")


class QwenTextProvider(TextProvider):
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = (api_key if api_key is not None else os.getenv("DASHSCOPE_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL).strip()
        self.model = (model or os.getenv("DASHSCOPE_TEXT_MODEL") or DEFAULT_MODEL).strip()

    def _client(self):
        if not self.api_key:
            raise TextAnalysisError("未配置百炼 API Key，已使用本地结果。")
        from openai import OpenAI
        return OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30.0)

    def _request(self, messages: list[dict[str, str]]) -> str:
        try:
            response = self._client().chat.completions.create(
                model=self.model, messages=messages, temperature=0.1, max_tokens=2500,
                response_format={"type": "json_object"}, extra_body={"enable_thinking": False},
            )
            return response.choices[0].message.content or "{}"
        except TextAnalysisError:
            raise
        except Exception as exc:
            logger.warning("Qwen text request failed: type=%s status=%s code=%s", type(exc).__name__,
                           getattr(exc, "status_code", None), getattr(exc, "code", None))
            raise self._friendly_error(exc) from None

    @staticmethod
    def _friendly_error(exc: Exception) -> TextAnalysisError:
        text, name, status = str(exc).lower(), type(exc).__name__.lower(), getattr(exc, "status_code", None)
        if "timeout" in name or "timed out" in text:
            return TextAnalysisError("文本分析请求超时，已使用本地结果。")
        if status == 401 or "authentication" in name or "invalid api" in text:
            return TextAnalysisError("百炼 API Key 无效，已使用本地结果。")
        if status == 429 or "rate limit" in text or "ratelimit" in name:
            return TextAnalysisError("文本分析请求过于频繁，已使用本地结果。")
        if status == 404 or "model_not_found" in text or "model not found" in text:
            return TextAnalysisError("百炼文本模型名不可用，已使用本地结果。")
        return TextAnalysisError("文本分析服务暂时不可用，已使用本地结果。")

    def analyze_item(self, item_name: str, normalized_name: str, pet_profile: PetProfile,
                     local_matches: list[dict], vision_result: VisionResult | None = None) -> AnalysisResult:
        vision_text = vision_result.model_dump(include={"item_name", "normalized_name", "visible_text",
                                                        "candidate_names", "confidence", "description", "uncertainty"}) if vision_result else None
        context = {"item_name": item_name, "normalized_name": normalized_name,
                   "pet_profile": pet_profile.model_dump(), "local_knowledge": local_matches,
                   "vision_text_fields": vision_text, "required_json_schema": AnalysisResult.model_json_schema()}
        prompt = "请根据以下内容输出完整 JSON：\n" + json.dumps(context, ensure_ascii=False)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        raw = self._request(messages)
        try:
            return parse_analysis_result(raw)
        except TextAnalysisError:
            repaired = self._request([
                {"role": "system", "content": "你是 JSON 修复器。只输出满足给定 schema 的 JSON，不增加任何事实或来源。"},
                {"role": "user", "content": prompt + "\n待修复内容：\n" + raw[:8000]},
            ])
            return parse_analysis_result(repaired)
