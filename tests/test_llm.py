import json

import pytest

from committee.llm import ChatError, OpenRouterClient, extract_json, parse_usage
from committee.run import parse_proposal


def test_parse_usage_from_openrouter_payload():
    usage = parse_usage(
        {
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 350,
                "total_tokens": 1550,
                "cost": 0.0042,
            }
        }
    )
    assert usage.prompt_tokens == 1200
    assert usage.completion_tokens == 350
    assert usage.cost_usd == 0.0042


def test_parse_usage_accepts_input_output_aliases():
    usage = parse_usage({"usage": {"input_tokens": 10, "output_tokens": 5}})
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15


def test_extract_json_strips_fences():
    data = extract_json("```json\n{\"squad\": [1], \"xi\": []}\n```")
    assert data["squad"] == [1]


def test_extract_json_strips_trailing_commas():
    data = extract_json('{"squad": [1, 2,], "xi": [],}')
    assert data["squad"] == [1, 2]


def test_parse_proposal_accepts_aliases():
    raw = """
    Here you go
    {
      "squad": [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],
      "xi": [1,3,4,5,8,9,10,11,12,13,14],
      "captain": 13,
      "vice": 8,
      "formation": "3-5-2",
      "rationale": "ok",
      "transfers": [{"out": 15, "in": 24}],
      "chip": "none",
      "hits": 0
    }
    """
    proposal = parse_proposal(raw)
    assert proposal.vice_captain == 8
    assert proposal.chip is None
    assert proposal.transfers[0].out_id == 15
    assert proposal.transfers[0].in_id == 24


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_openrouter_http_error_keeps_usage(monkeypatch):
    payload = {
        "error": {"message": "nope"},
        "usage": {
            "prompt_tokens": 9,
            "completion_tokens": 1,
            "total_tokens": 10,
            "cost": 0.0004,
        },
    }
    monkeypatch.setattr(
        "committee.llm.httpx.post",
        lambda *args, **kwargs: FakeResponse(400, payload),
    )
    with pytest.raises(ChatError) as excinfo:
        OpenRouterClient("k").complete("m", [{"role": "user", "content": "hi"}])
    assert excinfo.value.usage.cost_usd == 0.0004
    assert excinfo.value.usage.prompt_tokens == 9


def test_openrouter_empty_content_retries_then_keeps_usage(monkeypatch):
    payload = {
        "choices": [{"message": {"content": ""}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 0, "cost": 0.0001},
    }
    monkeypatch.setattr(
        "committee.llm.httpx.post",
        lambda *args, **kwargs: FakeResponse(200, payload),
    )
    with pytest.raises(ChatError) as excinfo:
        OpenRouterClient("k").complete("m", [{"role": "user", "content": "hi"}])
    assert "empty content" in str(excinfo.value)
    assert excinfo.value.usage.prompt_tokens == 24
    assert excinfo.value.usage.cost_usd == 0.0002


def test_openrouter_retries_without_json_mode(monkeypatch):
    calls: list[dict] = []
    ok = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "cost": 0.0},
    }

    def fake_post(*args, **kwargs):
        body = kwargs["json"]
        calls.append(body)
        if "response_format" in body:
            text = "No endpoints found that support the requested parameters"
            return FakeResponse(400, {"error": {"message": text}}, text=text)
        return FakeResponse(200, ok)

    monkeypatch.setattr("committee.llm.httpx.post", fake_post)
    result = OpenRouterClient("k").complete(
        "z-ai/glm-4.5-air",
        [{"role": "user", "content": "hi"}],
    )
    assert result.content == '{"ok": true}'
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert calls[0]["provider"] == {"sort": "price", "require_parameters": True}
    assert calls[1]["provider"] == {"sort": "price"}
    assert calls[1]["reasoning"] == {"enabled": False, "exclude": True}


def test_openrouter_retries_when_reasoning_is_mandatory(monkeypatch):
    calls: list[dict] = []
    ok = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "cost": 0.0002},
    }

    def fake_post(*args, **kwargs):
        body = kwargs["json"]
        calls.append(body)
        if body.get("reasoning", {}).get("enabled") is True:
            return FakeResponse(200, ok)
        text = "Reasoning is mandatory for this endpoint and cannot be disabled."
        return FakeResponse(400, {"error": {"message": text}}, text=text)

    monkeypatch.setattr("committee.llm.httpx.post", fake_post)
    result = OpenRouterClient("k").complete(
        "google/gemini-3.7-flash",
        [{"role": "user", "content": "hi"}],
    )
    assert result.content == '{"ok": true}'
    assert calls[1]["reasoning"]["enabled"] is True
    assert calls[1]["max_tokens"] == 2000


def test_openrouter_reads_gemini_list_content(monkeypatch):
    payload = {
        "choices": [{"message": {"content": [{"type": "text", "text": '{"ok": true}'}]}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "cost": 0.0},
    }
    monkeypatch.setattr(
        "committee.llm.httpx.post",
        lambda *args, **kwargs: FakeResponse(200, payload),
    )
    result = OpenRouterClient("k").complete("google/gemini-3.7-flash", [{"role": "user", "content": "hi"}])
    assert result.content == '{"ok": true}'
