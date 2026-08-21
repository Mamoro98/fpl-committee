import json
import re
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _affordable_tokens(body: str) -> int | None:
    match = re.search(r"can only afford (\d+)", body)
    return int(match.group(1)) if match else None


def _json_unsupported(status_code: int, body: str) -> bool:
    if status_code not in {400, 404}:
        return False
    lowered = body.lower()
    return "no endpoints found" in lowered or "response_format" in lowered


def _reasoning_mandatory(status_code: int, body: str) -> bool:
    return status_code in {400, 404} and "reasoning is mandatory" in body.lower()


def _reasoning_unsupported(status_code: int, body: str) -> bool:
    if status_code not in {400, 404}:
        return False
    lowered = body.lower()
    return "reasoning" in lowered and (
        "no endpoints found" in lowered or "not supported" in lowered or "unknown" in lowered
    )


def _message_text(message: dict) -> str:
    content = message.get("content") or ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text") or "")
            else:
                parts.append(str(part))
        content = "".join(parts)
    if not str(content).strip():
        content = message.get("reasoning") or ""
    return str(content)


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 8),
        )


class ChatResult(BaseModel):
    content: str
    usage: Usage = Field(default_factory=Usage)


class ChatError(RuntimeError):
    def __init__(self, message: str, usage: Usage | None = None, content: str = "") -> None:
        super().__init__(message)
        self.usage = usage or Usage()
        self.content = content


class ChatClient(Protocol):
    def complete(
        self,
        model: str,
        messages: list[dict],
        *,
        max_tokens: int = 800,
    ) -> ChatResult: ...


def parse_usage(payload: dict) -> Usage:
    usage = payload.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    cost = usage.get("cost", usage.get("total_cost"))
    if cost is None:
        details = usage.get("cost_details") or {}
        cost = details.get("upstream_inference_cost") or 0
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost_usd=float(cost or 0),
    )


def _usage_from_response(response: object) -> Usage:
    try:
        parsed = response.json()  # type: ignore[attr-defined]
    except Exception:
        return Usage()
    if isinstance(parsed, dict):
        return parse_usage(parsed)
    return Usage()


def sum_usage(usages: list[Usage]) -> Usage:
    total = Usage()
    for item in usages:
        total = total + item
    return total


class OpenRouterClient:
    def __init__(self, api_key: str, timeout: float = 180) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def complete(
        self,
        model: str,
        messages: list[dict],
        *,
        max_tokens: int = 800,
        json_mode: bool = True,
        reasoning: str | None = None,
        _spent: Usage | None = None,
    ) -> ChatResult:
        spent = _spent or Usage()
        provider: dict = {"sort": "price"}
        if json_mode:
            provider["require_parameters"] = True
        body: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "provider": provider,
            "usage": {"include": True},
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if reasoning == "cap":
            body["reasoning"] = {"max_tokens": 800, "exclude": True}
        elif reasoning == "on":
            body["reasoning"] = {"enabled": True, "exclude": True}
        elif reasoning == "off":
            body["reasoning"] = {"enabled": False, "exclude": True}
        response = httpx.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/fpl-committee",
                "X-Title": "fpl-committee",
            },
            json=body,
            timeout=self._timeout,
        )
        if response.status_code == 402:
            affordable = _affordable_tokens(response.text)
            if affordable and affordable < max_tokens and affordable >= 256:
                return self.complete(
                    model,
                    messages,
                    max_tokens=affordable,
                    json_mode=json_mode,
                    reasoning=reasoning,
                    _spent=spent,
                )
        if json_mode and _json_unsupported(response.status_code, response.text):
            return self.complete(
                model,
                messages,
                max_tokens=max_tokens,
                json_mode=False,
                reasoning="off",
                _spent=spent + _usage_from_response(response),
            )
        if _reasoning_mandatory(response.status_code, response.text) and reasoning != "on":
            return self.complete(
                model,
                messages,
                max_tokens=max(max_tokens, 2000),
                json_mode=json_mode,
                reasoning="on",
                _spent=spent + _usage_from_response(response),
            )
        if reasoning is not None and _reasoning_unsupported(response.status_code, response.text):
            return self.complete(
                model,
                messages,
                max_tokens=max_tokens,
                json_mode=json_mode,
                reasoning=None,
                _spent=spent + _usage_from_response(response),
            )
        usage = spent + _usage_from_response(response)
        payload: dict = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            pass
        if response.status_code >= 400:
            raise ChatError(
                f"OpenRouter {response.status_code}: {response.text[:800]}",
                usage=usage,
                content=response.text[:800],
            )
        message = payload.get("choices", [{}])[0].get("message") or {}
        content = _message_text(message)
        finish = payload.get("choices", [{}])[0].get("finish_reason")
        if finish in {"length", "max_tokens"} and max_tokens < 4000:
            return self.complete(
                model,
                messages,
                max_tokens=min(max(max_tokens * 2, 2000), 4000),
                json_mode=json_mode,
                reasoning=reasoning or "cap",
                _spent=usage,
            )
        if not content.strip() and reasoning is None:
            return self.complete(
                model,
                messages,
                max_tokens=max(max_tokens, 2000),
                json_mode=json_mode,
                reasoning="cap",
                _spent=usage,
            )
        if not content.strip():
            raise ChatError(f"{model} returned empty content", usage=usage, content=content)
        return ChatResult(content=content, usage=usage)


def extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    candidates = [stripped]
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    last_error: Exception | None = None
    seen: set[str] = set()
    for candidate in candidates:
        for payload in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            if payload in seen:
                continue
            seen.add(payload)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(data, dict):
                return data
            last_error = ValueError("JSON payload is not an object")
    preview = stripped[:240].replace("\n", " ")
    detail = f"{last_error}: {preview}" if last_error else preview
    raise ValueError(f"model output was not valid JSON ({detail})")
