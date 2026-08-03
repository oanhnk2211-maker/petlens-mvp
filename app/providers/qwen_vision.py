from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from pydantic import ValidationError

from app.providers.vision_base import VisionError, VisionProvider, VisionResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-vl-flash"
SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}

VISION_PROMPT = """识别图片中最主要、最可能被用户查询的一个物品。你只负责识别物品，禁止输出任何宠物安全结论。
要求：
- 优先给出用户容易理解的通用物品名称，不要只给品牌名；
- 食品包装应结合包装文字与可见内容物判断；
- 药品应识别药名或有效成分；
- 植物无法确定具体品种时必须明确表达不确定，不得强行猜测；
- 不确定时降低 confidence 并填写 uncertainty；
- 只输出严格 JSON，不要 Markdown 或解释。
JSON 字段必须是：item_name、normalized_name、visible_text、candidate_names、confidence、description、uncertainty。
confidence 必须是 0 到 1 之间的数字；visible_text 和 candidate_names 必须是字符串数组。"""


def image_to_data_url(image_bytes: bytes, media_type: str) -> str:
    normalized = media_type.lower().split(";", 1)[0].strip()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    if normalized not in SUPPORTED_MEDIA_TYPES:
        raise VisionError("图片格式不支持，请上传 JPEG、PNG 或 WebP 图片。")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{normalized};base64,{encoded}"


def parse_vision_result(text: str) -> VisionResult:
    decoder = json.JSONDecoder()
    candidates = [text.strip()]
    if "```" in text:
        parts = text.split("```")
        candidates.extend(part[4:].strip() if part.lstrip().startswith("json") else part.strip() for part in parts[1::2])
    candidates.extend(text[index:] for index, char in enumerate(text) if char == "{")
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate.lstrip())
            if isinstance(value, dict):
                return VisionResult.model_validate(value)
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
            continue
    raise VisionError("模型返回格式错误，请重新识别或手动输入名称。")


class QwenVisionProvider(VisionProvider):
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = (api_key if api_key is not None else os.getenv("DASHSCOPE_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL).strip()
        self.model = (model or os.getenv("DASHSCOPE_VISION_MODEL") or DEFAULT_MODEL).strip()

    def _client(self):
        if not self.api_key:
            raise VisionError("未配置 API Key，请在 .env 中设置 DASHSCOPE_API_KEY，或手动输入物品名称。")
        from openai import OpenAI
        return OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30.0)

    @staticmethod
    def _message_text(response: Any) -> str:
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "") for part in content)
        return ""

    def _request(self, messages: list[dict[str, Any]]) -> str:
        try:
            response = self._client().chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=700,
            )
            return self._message_text(response)
        except VisionError:
            raise
        except Exception as exc:
            logger.warning(
                "Qwen vision request failed: type=%s status=%s code=%s",
                type(exc).__name__, getattr(exc, "status_code", None), getattr(exc, "code", None),
            )
            raise self._friendly_error(exc) from None

    @staticmethod
    def _friendly_error(exc: Exception) -> VisionError:
        name = type(exc).__name__.lower()
        message = str(exc).lower()
        status = getattr(exc, "status_code", None)
        if "timeout" in name or "timed out" in message:
            return VisionError("网络请求超时，请稍后重试。")
        if status == 401 or "authentication" in name or "invalid api-key" in message or "invalid api key" in message:
            return VisionError("API Key 无效，请检查 DASHSCOPE_API_KEY。")
        if status == 402 or any(word in message for word in ("insufficient_quota", "quota", "balance", "余额")):
            return VisionError("账户余额或调用额度不足，请检查百炼控制台。")
        if status == 429 or "ratelimit" in name or "rate limit" in message:
            return VisionError("请求过于频繁，请稍后重试。")
        if status == 404 or "model_not_found" in message or "model not found" in message:
            return VisionError("模型名无效，请检查 DASHSCOPE_VISION_MODEL。")
        return VisionError("图片识别服务暂时不可用，请稍后重试或手动输入名称。")

    def recognize(self, image_bytes: bytes, media_type: str) -> VisionResult:
        data_url = image_to_data_url(image_bytes, media_type)
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }]
        raw = self._request(messages)
        try:
            return parse_vision_result(raw)
        except VisionError:
            repair = self._request([
                {"role": "system", "content": "你是 JSON 格式修复器，只输出修复后的严格 JSON，不增加事实。"},
                {"role": "user", "content": VISION_PROMPT + "\n待修复内容：\n" + raw[:6000]},
            ])
            return parse_vision_result(repair)
