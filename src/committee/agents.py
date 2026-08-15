import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

PROMPTS_DIR = Path(__file__).parent / "prompts"

AGENTS = ["scout", "risk", "hawk"]

DEFAULT_MODELS = {
    "scout": "openai/gpt-5-mini",
    "risk": "deepseek/deepseek-v3.2",
    "hawk": "google/gemini-3.7-flash",
}


class Suggestion(BaseModel):
    agent: str
    transfer_in: int
    transfer_out: int
    captain: int
    bench_order: list[int] = []
    rationale: str = ""
    attacks: list[str] = []


class AgentResponseError(Exception):
    pass


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in response")
    return json.loads(match.group())


def system_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def run_agent(
    name: str,
    client,
    context: str,
    model: str | None = None,
    response_model: type[BaseModel] = Suggestion,
):
    model = model or DEFAULT_MODELS[name]
    system = system_prompt(name)
    last_error = None
    for _ in range(2):
        raw = client.complete(model=model, system=system, user=context)
        try:
            data = _extract_json(raw)
            data["agent"] = name
            return response_model(**data)
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
    raise AgentResponseError(f"{name} returned invalid JSON twice: {last_error}")
