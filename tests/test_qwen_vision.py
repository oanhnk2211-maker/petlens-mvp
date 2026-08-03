from types import SimpleNamespace

import pytest

from app.knowledge import find_local_matches
from app.providers.mock_vision import MockVisionProvider
from app.providers.qwen_vision import QwenVisionProvider, image_to_data_url, parse_vision_result
from app.providers.vision_base import VisionError, VisionResult, recognize_once


VALID = {
    "item_name": "黑巧克力",
    "normalized_name": "巧克力",
    "visible_text": ["70% CACAO"],
    "candidate_names": ["可可制品"],
    "confidence": 0.92,
    "description": "一块深色包装的巧克力",
    "uncertainty": "",
}


@pytest.mark.parametrize(
    ("media_type", "prefix"),
    [
        ("image/jpeg", "data:image/jpeg;base64,"),
        ("image/png", "data:image/png;base64,"),
        ("image/webp", "data:image/webp;base64,"),
    ],
)
def test_image_to_matching_data_url(media_type, prefix):
    assert image_to_data_url(b"image bytes", media_type).startswith(prefix)


def test_parse_plain_json():
    import json
    assert parse_vision_result(json.dumps(VALID, ensure_ascii=False)).normalized_name == "巧克力"


def test_parse_markdown_json_and_surrounding_text():
    import json
    text = "识别如下：\n```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```\n完成"
    assert parse_vision_result(text).visible_text == ["70% CACAO"]


def test_bad_json_raises_readable_error():
    with pytest.raises(VisionError, match="模型返回格式错误"):
        parse_vision_result("{bad json")


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_in_range(confidence):
    value = {**VALID, "confidence": confidence}
    import json
    with pytest.raises(VisionError):
        parse_vision_result(json.dumps(value))


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(VisionError, match="未配置 API Key"):
        QwenVisionProvider(api_key="").recognize(b"x", "image/jpeg")


class FakeApiError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (FakeApiError("invalid api key", 401), "API Key 无效"),
        (TimeoutError("timed out"), "网络请求超时"),
    ],
)
def test_api_errors_are_translated(monkeypatch, error, message):
    provider = QwenVisionProvider(api_key="test-key")
    completions = SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(error))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(provider, "_client", lambda: client)
    with pytest.raises(VisionError, match=message):
        provider.recognize(b"x", "image/jpeg")


def test_same_image_is_not_called_twice():
    expected = VisionResult.model_validate(VALID)
    provider = MockVisionProvider(expected)
    state = {}
    first = recognize_once(provider, b"same", "image/png", state)
    second = recognize_once(provider, b"same", "image/png", state)
    assert first == second
    assert provider.calls == 1


def test_user_edited_name_queries_local_knowledge():
    # The editable value, rather than the model's original name, enters the local lookup.
    recognized = VisionResult.model_validate(VALID)
    edited_name = "葡萄"
    assert edited_name != recognized.item_name
    assert find_local_matches(edited_name, "狗")[0]["item"] == "葡萄或葡萄干"
