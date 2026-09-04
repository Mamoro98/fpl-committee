import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, model_validator

PROMPTS_DIR = Path(__file__).parent / "prompts"

AGENTS = ["scout", "risk", "hawk"]

DEFAULT_MODELS = {
    "scout": "openai/gpt-5-mini",
    "risk": "deepseek/deepseek-v3.2",
    "hawk": "google/gemini-3.7-flash",
}


CHIPS = ("wildcard", "freehit", "bboost", "3xc")


class Transfer(BaseModel):
    out: int
    in_: int = Field(alias="in")

    model_config = {"populate_by_name": True}


class Suggestion(BaseModel):
    """One agent's advice. `transfers` is the source of truth; transfer_in/out
    mirror the first transfer so older code keeps working."""

    agent: str
    transfers: list[Transfer] = []
    transfer_in: int | None = None
    transfer_out: int | None = None
    chip: str | None = None
    captain: int
    bench_order: list[int] = []
    rationale: str = ""
    attacks: list[str] = []

    @model_validator(mode="after")
    def _sync_transfers(self):
        if not self.transfers and self.transfer_in is not None and self.transfer_out is not None:
            self.transfers = [Transfer(out=self.transfer_out, **{"in": self.transfer_in})]
        if self.transfers:
            self.transfer_in = self.transfers[0].in_
            self.transfer_out = self.transfers[0].out
        if self.chip is not None:
            self.chip = self.chip.lower().replace("_", "").replace(" ", "")
            if self.chip in ("none", "null", ""):
                self.chip = None
            elif self.chip not in CHIPS:
                raise ValueError(f"unknown chip {self.chip!r}, allowed: {CHIPS}")
        return self

    @property
    def transfer_ins(self) -> list[int]:
        return [t.in_ for t in self.transfers]

    @property
    def transfer_outs(self) -> list[int]:
        return [t.out for t in self.transfers]


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


def suggestion_dict(s: Suggestion) -> dict:
    """Serialise with the public 'in' key so saved files read naturally."""
    return s.model_dump(by_alias=True)


def transfers_of(s: dict) -> list[tuple[int, int]]:
    """(out, in) pairs from a saved suggestion dict, old or new shape."""
    pairs = []
    for t in s.get("transfers") or []:
        pairs.append((t["out"], t.get("in", t.get("in_"))))
    if not pairs and s.get("transfer_in") is not None and s.get("transfer_out") is not None:
        pairs.append((s["transfer_out"], s["transfer_in"]))
    return pairs
