from pathlib import Path
import json

import pytest

from committee.cli import format_recommendation, main
from committee.llm import Usage
from committee.schema import Memo, Recommendation, SquadProposal
from tests.helpers import LEGAL_SQUAD, LEGAL_XI, POOL


def _rec() -> Recommendation:
    proposal = SquadProposal(
        squad=list(LEGAL_SQUAD),
        xi=list(LEGAL_XI),
        captain=13,
        vice_captain=8,
        formation="3-5-2",
        rationale="Haaland captain.",
    )
    return Recommendation(
        gameweek=1,
        mode="pick",
        squad_ids=list(LEGAL_SQUAD),
        xi=list(LEGAL_XI),
        captain=13,
        vice_captain=8,
        formation="3-5-2",
        budget_used=100.0,
        bank=0.0,
        locked_ids=[13, 8],
        rationale="Haaland captain.",
        memos=[
            Memo(
                model="deepseek",
                model_id="m-deepseek",
                role="member",
                gameweek=1,
                mode="pick",
                proposal=proposal,
                usage=Usage(prompt_tokens=80, completion_tokens=20, total_tokens=100, cost_usd=0.0015),
            )
        ],
        usage=Usage(prompt_tokens=80, completion_tokens=20, total_tokens=100, cost_usd=0.0015),
    )


def test_format_recommendation_lists_captain():
    text = format_recommendation(_rec(), POOL)
    assert "Haaland" in text
    assert "Captain" in text
    assert "does not submit" in text
    assert "in      80" in text
    assert "$0.001500" in text


def test_pick_cli_writes_memos_and_ledger(monkeypatch, tmp_path: Path, capsys):
    rec = _rec()

    class DummyClient:
        def get_players(self):
            return POOL

    class DummyCommittee:
        client = DummyClient()

        def pick(self):
            return rec

    monkeypatch.setattr("committee.cli.build_committee", lambda: (DummyCommittee(), None))
    memos = tmp_path / "memos"
    ledger = tmp_path / "ledger.json"
    code = main(["--memos-dir", str(memos), "--ledger", str(ledger), "pick"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Haaland" in out
    assert (memos / "gw1" / "member-deepseek.json").exists()
    assert ledger.exists()
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert saved[0]["usage"]["prompt_tokens"] == 80
    assert saved[0]["usage"]["cost_usd"] == 0.0015
    assert saved[0]["usage_by_call"][0]["model"] == "deepseek"


def test_format_marks_failed_usage():
    rec = _rec()
    rec.memos.append(
        Memo(
            model="glm",
            model_id="m-glm",
            role="member",
            gameweek=1,
            mode="pick",
            error="OpenRouter 400: provider exploded",
            usage=Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12, cost_usd=0.0004),
        )
    )
    text = format_recommendation(rec, POOL)
    assert "FAILED" in text
    assert "provider exploded" in text


def test_pick_cli_persists_even_when_squad_errors(monkeypatch, tmp_path: Path, capsys):
    rec = _rec()
    rec.errors = ["squad must have 15 players"]
    rec.memos.append(
        Memo(
            model="glm",
            model_id="m-glm",
            role="member",
            gameweek=1,
            mode="pick",
            error="OpenRouter 400: provider exploded",
            usage=Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12, cost_usd=0.0004),
        )
    )
    rec.refresh_usage()

    class DummyClient:
        def get_players(self):
            return POOL

    class DummyCommittee:
        client = DummyClient()

        def pick(self):
            return rec

    monkeypatch.setattr("committee.cli.build_committee", lambda: (DummyCommittee(), None))
    memos = tmp_path / "memos"
    ledger = tmp_path / "ledger.json"
    code = main(["--memos-dir", str(memos), "--ledger", str(ledger), "pick"])
    assert code == 1
    captured = capsys.readouterr()
    assert "squad must have 15 players" in captured.err
    assert "FAILED" in captured.out
    assert (memos / "gw1" / "member-glm.json").exists()
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert saved[0]["errors"] == ["squad must have 15 players"]
    assert saved[0]["usage"]["cost_usd"] == 0.0019
    glm = next(row for row in saved[0]["usage_by_call"] if row["model"] == "glm")
    assert glm["error"] == "OpenRouter 400: provider exploded"
    assert glm["cost_usd"] == 0.0004


def test_week_cli_requires_team_id():
    with pytest.raises(SystemExit):
        main(["week"])
