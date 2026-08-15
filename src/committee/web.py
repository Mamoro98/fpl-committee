import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from committee.agents import AGENTS
from committee.cli import (
    LEDGER_PATH,
    MEMOS_DIR,
    build_context,
    get_squad_for_gw,
    load_ledger,
)
from committee.debate import run_debate
from committee.draft import run_draft_debate
from committee.draft_memo import draft_thread, render_draft_memo
from committee.fpl import FplClient
from committee.llm import LlmClient
from committee.manual import load_manual_squad, resolve_names, save_manual_squad
from committee.memo import debate_thread, render_memo

app = FastAPI(title="fpl-committee")

INDEX_PATH = Path(__file__).parent / "static" / "index.html"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


def _squad_players(snapshot, lookup) -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "price": p.price,
            "status": p.status,
        }
        for pid in snapshot.player_ids
        if (p := lookup.get(pid))
    ]


@app.get("/api/squad")
def squad() -> dict:
    fpl = FplClient()
    entry_id = os.environ.get("FPL_ENTRY_ID")
    gw = fpl.get_current_gw() if entry_id else None
    if entry_id and gw is not None:
        snapshot = fpl.get_squad(int(entry_id), gw)
        if snapshot is not None:
            lookup = {p.id: p for p in fpl.get_players()}
            return {
                "squad": _squad_players(snapshot, lookup),
                "bank": snapshot.bank,
                "gw": gw,
                "source": "fpl",
            }

    manual = load_manual_squad()
    if manual is not None:
        lookup = {p.id: p for p in fpl.get_players()}
        return {
            "squad": _squad_players(manual, lookup),
            "bank": manual.bank,
            "gw": None,
            "source": "manual",
        }

    return {
        "squad": None,
        "reason": "No squad yet. Paste your team below, or wait for GW1 to be played",
    }


class ManualSquadPayload(BaseModel):
    names: list[str]
    bank: float


@app.post("/api/squad/manual")
def set_manual_squad(payload: ManualSquadPayload) -> dict:
    players = FplClient().get_players()
    resolved, unmatched = resolve_names(payload.names, players)
    if unmatched:
        return {"ok": False, "unmatched": unmatched, "matched": len(resolved)}
    if len(resolved) != 15:
        return {
            "ok": False,
            "unmatched": [],
            "matched": len(resolved),
            "detail": f"a squad is 15 players, you gave {len(resolved)}",
        }
    save_manual_squad([p.id for p in resolved], payload.bank)
    return {"ok": True, "matched": len(resolved)}


@app.get("/api/scoreboard")
def scoreboard() -> dict:
    ledger = load_ledger()
    return {"scores": ledger.scores(), "history": ledger.history()}


@app.post("/api/draft")
def draft() -> dict:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    result = run_draft_debate(client, players, ledger)

    MEMOS_DIR.mkdir(exist_ok=True)
    memo = render_draft_memo(result, ledger, players)
    (MEMOS_DIR / "draft.md").write_text(memo, encoding="utf-8")
    return {"memo": memo, "thread": draft_thread(result, players)}


@app.post("/api/memo/{gw}")
def memo(gw: int) -> dict:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    squad = get_squad_for_gw(fpl, gw)
    context = build_context(players, gw, squad=squad)
    result = run_debate(client, context, ledger)

    MEMOS_DIR.mkdir(exist_ok=True)
    names = {p.id: p.name for p in players}
    text = render_memo(result, ledger, gw, players=names)
    (MEMOS_DIR / f"gw{gw}.md").write_text(text, encoding="utf-8")
    (MEMOS_DIR / f"gw{gw}_suggestions.json").write_text(
        json.dumps(
            {agent: s.model_dump() for agent, s in result["final"].items()}, indent=2
        ),
        encoding="utf-8",
    )
    return {"memo": text, "agents": AGENTS, "thread": debate_thread(result, names)}


@app.post("/api/pick/{gw}/{agent}")
def pick(gw: int, agent: str) -> dict:
    suggestions_path = MEMOS_DIR / f"gw{gw}_suggestions.json"
    if not suggestions_path.exists():
        raise HTTPException(404, f"no memo for GW{gw}, run the debate first")
    suggestions = json.loads(suggestions_path.read_text(encoding="utf-8"))
    if agent not in suggestions:
        raise HTTPException(400, f"unknown agent {agent}")

    ledger = load_ledger()
    if any(e["gw"] == gw for e in ledger.history()):
        raise HTTPException(409, f"GW{gw} already has a pick")
    ledger.record_pick(gw=gw, agent=agent, suggestion=suggestions[agent])
    ledger.save(LEDGER_PATH)
    return {"picked": agent, "gw": gw}


@app.post("/api/settle/{gw}")
def settle(gw: int) -> dict:
    ledger = load_ledger()
    entry = next((e for e in ledger.history() if e["gw"] == gw), None)
    if entry is None:
        raise HTTPException(404, f"no pick recorded for GW{gw}")
    if entry["reward"] is not None:
        raise HTTPException(409, f"GW{gw} already settled")

    suggestion = entry["suggestion"]
    points = FplClient().get_gw_points(gw)
    reward = float(
        10
        + points.get(suggestion["transfer_in"], 0)
        + points.get(suggestion["captain"], 0)
    )
    ledger.settle(gw=gw, reward=reward)
    ledger.save(LEDGER_PATH)
    return {"picked": entry["picked"], "reward": reward, "scores": ledger.scores()}
