import json

from committee.config import Settings
from committee.fpl import Entry, FplClient
from committee.llm import ChatError, ChatResult, Usage
from committee.run import Committee
from tests.helpers import GW1, LEGAL_SQUAD, LEGAL_XI, POOL, TEAMS


def _json_proposal(**overrides) -> str:
    payload = {
        "squad": list(LEGAL_SQUAD),
        "xi": list(LEGAL_XI),
        "captain": 13,
        "vice_captain": 8,
        "formation": "3-5-2",
        "rationale": "consensus",
        "transfers": [],
        "chip": None,
        "hits": 0,
    }
    payload.update(overrides)
    return json.dumps(payload)


CALL_USAGE = Usage(prompt_tokens=100, completion_tokens=40, total_tokens=140, cost_usd=0.002)
MEMBER_IDS = {
    "m-deepseek": "deepseek",
    "m-gptoss": "gptoss",
    "m-qwen": "qwen",
    "m-mistral": "mistral",
    "m-gemini": "gemini",
}


class FakeChat:
    def __init__(
        self,
        replies: dict[str, list[str]],
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.replies = {k: list(v) for k, v in replies.items()}
        self.errors = errors or {}
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, model: str, messages: list[dict], *, max_tokens: int = 800) -> ChatResult:
        self.calls.append((model, messages))
        if model in self.errors:
            raise self.errors[model]
        queue = self.replies[model]
        return ChatResult(content=queue.pop(0), usage=CALL_USAGE)


class FakeFpl(FplClient):
    def get_players(self):
        return POOL

    def get_teams(self):
        return TEAMS

    def get_fixtures(self):
        return []

    def get_target_event(self):
        return GW1

    def get_entry(self, team_id: int, free_transfers: int = 1) -> Entry:
        return Entry(
            id=team_id,
            name="dummy",
            current_event=1,
            bank=0.5,
            squad_ids=list(LEGAL_SQUAD),
            xi_ids=list(LEGAL_XI),
            captain_id=13,
            vice_captain_id=8,
            free_transfers=free_transfers,
        )


def _settings() -> Settings:
    return Settings(
        api_key="test",
        models=[(name, slug) for slug, name in MEMBER_IDS.items()],
        max_tokens=800,
    )


def _legal_replies() -> dict[str, list[str]]:
    legal = _json_proposal()
    return {slug: [legal] for slug in MEMBER_IDS}


def test_pick_vote_lock_and_code_chair():
    chat = FakeChat(_legal_replies())
    rec = Committee(chat, _settings(), FakeFpl()).pick()
    assert rec.squad_ids == LEGAL_SQUAD
    assert rec.captain == 13
    assert rec.gameweek == 1
    assert rec.mode == "pick"
    assert set(rec.locked_ids) == set(LEGAL_SQUAD)
    assert rec.budget_used == 100.0
    assert any(m.role == "chair" and m.model == "greedy" for m in rec.memos)
    assert {m.model for m in rec.memos if m.role == "member"} == set(MEMBER_IDS.values())
    assert len(chat.calls) == 5
    assert rec.usage.prompt_tokens == 500
    assert rec.usage.cost_usd == 0.01


def test_invalid_member_json_is_recorded():
    replies = _legal_replies()
    replies["m-qwen"] = ["not json"]
    chat = FakeChat(replies)
    rec = Committee(chat, _settings(), FakeFpl()).pick()
    assert rec.squad_ids == LEGAL_SQUAD
    qwen = next(m for m in rec.memos if m.model == "qwen")
    assert qwen.proposal is None
    assert qwen.error is not None
    assert qwen.usage == CALL_USAGE
    assert rec.usage.prompt_tokens == 500
    assert rec.usage.cost_usd == 0.01
    assert len(chat.calls) == 5


FAIL_USAGE = Usage(prompt_tokens=50, completion_tokens=0, total_tokens=50, cost_usd=0.0007)


def test_http_error_usage_is_recorded():
    chat = FakeChat(
        _legal_replies(),
        errors={"m-qwen": ChatError("OpenRouter 400: provider error", usage=FAIL_USAGE, content="nope")},
    )
    rec = Committee(chat, _settings(), FakeFpl()).pick()
    qwen = next(m for m in rec.memos if m.model == "qwen")
    assert qwen.proposal is None
    assert "provider error" in (qwen.error or "")
    assert qwen.usage == FAIL_USAGE
    assert rec.usage.prompt_tokens == 450
    assert rec.usage.cost_usd == 0.0087
    assert rec.errors == []


def test_all_http_failures_still_record_cost():
    chat = FakeChat(
        {slug: ["unused"] for slug in MEMBER_IDS},
        errors={
            slug: ChatError("OpenRouter 402: insufficient credits", usage=FAIL_USAGE)
            for slug in MEMBER_IDS
        },
    )
    rec = Committee(chat, _settings(), FakeFpl()).pick()
    members = [m for m in rec.memos if m.role == "member"]
    assert len(members) == 5
    assert all(m.error and m.usage == FAIL_USAGE for m in members)
    assert rec.usage.prompt_tokens == 250
    assert rec.usage.cost_usd == 0.0035


def test_week_no_transfers():
    chat = FakeChat(_legal_replies())
    rec = Committee(chat, _settings(), FakeFpl()).week(99, free_transfers=1)
    assert rec.mode == "week"
    assert rec.transfers == []
    assert rec.hits == 0
    assert rec.bank == 0.5
    assert len(chat.calls) == 5
