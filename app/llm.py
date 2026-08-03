from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from app.models import PetProfile, SafetyResult


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def recognize_image(image_bytes: bytes, media_type: str = "image/jpeg") -> dict[str, Any] | None:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("ANTHROPIC_MODEL", "").strip()
    if not key or not model:
        return None
    from anthropic import Anthropic
    client = Anthropic(api_key=key)
    payload = base64.b64encode(image_bytes).decode("utf-8")
    message = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": payload},
                },
                {
                    "type": "text",
                    "text": (
                        "识别图中用户最可能想查询的单个物品。只返回 JSON："
                        '{"item_name":"中文名称","alternatives":["候选1"],'
                        '"visual_notes":"与宠物安全有关的包装、成分、形态或尺寸信息"}'
                    ),
                },
            ],
        }],
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    return _extract_json(text)


def _system_prompt() -> str:
    return """你是宠物用品与中毒风险筛查助手。你必须：
1. 将食品、毒性、玩具性、物理危险、宠物兴趣视为可同时成立的五个维度，不做互斥分类。
2. 优先采用给定的本地知识库和检索证据；证据不足时明确降低置信度，禁止编造剂量和医学结论。
3. 对已误食、明显中毒或急症场景，建议立即联系兽医，而不是让用户等待观察。
4. 只输出符合给定 schema 的 JSON，不输出 Markdown。
5. 中文表达清楚、简短，但要指出关键例外。"""


def analyze_with_llm(item: str, profile: PetProfile, local_matches: list[dict], web_sources: list[dict]) -> SafetyResult | None:
    schema = SafetyResult.model_json_schema()
    context = {
        "item": item,
        "pet_profile": profile.model_dump(),
        "local_knowledge": local_matches,
        "web_sources": web_sources,
        "output_schema": schema,
    }
    prompt = "请综合以下信息完成风险筛查，并严格输出 JSON：\n" + json.dumps(context, ensure_ascii=False)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "").strip()
    if anthropic_key and anthropic_model:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        message = client.messages.create(
            model=anthropic_model,
            max_tokens=2500,
            system=_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        return SafetyResult.model_validate(_extract_json(text))

    compat_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "").strip()
    compat_base = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").strip()
    compat_model = os.getenv("OPENAI_COMPATIBLE_MODEL", "").strip()
    if compat_key and compat_base and compat_model:
        from openai import OpenAI
        client = OpenAI(api_key=compat_key, base_url=compat_base)
        response = client.chat.completions.create(
            model=compat_model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or "{}"
        return SafetyResult.model_validate(_extract_json(text))
    return None
