import json
import os
import threading
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from committee.agents import AGENTS
from committee.cli import (
    LEDGER_PATH,
    MEMOS_DIR,
    build_context,
    elite_n,
    get_squad_for_gw,
    load_ledger,
)
from committee.debate import run_debate
from committee.draft import run_draft_debate
from committee.draft_memo import draft_thread, render_draft_memo
from committee.elite import elite_block_for_gw
from committee.fpl import FplClient
from committee.history import build_agent_histories, build_debate_recap
from committee.llm import LlmClient
from committee.manual import load_manual_squad, resolve_names, save_manual_squad
from committee.memo import debate_thread, render_memo

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = FastAPI(title="fpl-committee")

INDEX_PATH = Path(__file__).parent / "static" / "index.html"

JOBS: dict[str, dict] = {}


def _run_job(job_id: str, fn) -> None:
    job = JOBS[job_id]
    try:
        job["result"] = fn()
        job["state"] = "done"
    except Exception as exc:  # noqa: BLE001 - job boundary, every failure must reach the UI
        job["state"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[job {job_id}] failed: {job['error']}")


def _start_job(label: str, fn) -> dict:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "state": "running",
        "label": label,
        "started_at": time.time(),
        "result": None,
        "error": None,
    }
    threading.Thread(target=_run_job, args=(job_id, fn), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return {
        "state": job["state"],
        "label": job["label"],
        "elapsed": int(time.time() - job["started_at"]),
        "result": job["result"] if job["state"] == "done" else None,
        "error": job["error"],
    }


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
            "team_code": p.team_code,
            "slot": snapshot.slots.get(p.id),
            "is_captain": p.id == snapshot.captain,
            "is_vice": p.id == snapshot.vice,
        }
        for pid in snapshot.player_ids
        if (p := lookup.get(pid))
    ]


def _formation(starters: list) -> str:
    counts = {"DEF": 0, "MID": 0, "FWD": 0}
    for p in starters:
        if p.position in counts:
            counts[p.position] += 1
    return f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"


def _bench_is_legal(bench: list[int], ids: list[int], lookup) -> bool:
    if len(bench) != 4 or len(set(bench)) != 4:
        return False
    if any(pid not in ids or pid not in lookup for pid in bench):
        return False
    bench_gk = sum(1 for pid in bench if lookup[pid].position == "GKP")
    if bench_gk != 1:
        return False
    xi = [lookup[pid] for pid in ids if pid not in bench and pid in lookup]
    defenders = sum(1 for p in xi if p.position == "DEF")
    forwards = sum(1 for p in xi if p.position == "FWD")
    keepers = sum(1 for p in xi if p.position == "GKP")
    return keepers == 1 and defenders >= 3 and forwards >= 1


def build_proposals(squad, lookup, suggestions: dict) -> dict:
    proposals = {}
    for agent, s in suggestions.items():
        ids = [pid for pid in squad.player_ids if pid != s["transfer_out"]]
        if s["transfer_in"] not in ids:
            ids.append(s["transfer_in"])

        bench = [pid for pid in (s.get("bench_order") or []) if pid in ids][:4]
        bench_fixed = False
        if not _bench_is_legal(bench, ids, lookup):
            bench_fixed = True
            original_bench = sorted(
                (pid for pid, slot in squad.slots.items() if slot > 11),
                key=lambda pid: squad.slots[pid],
            )
            bench = [
                s["transfer_in"] if pid == s["transfer_out"] else pid
                for pid in original_bench
            ]
            bench = [pid for pid in bench if pid in ids][:4]

        captain = s["captain"]
        captain_fixed = False
        if captain not in ids or captain in bench:
            captain_fixed = True
            if squad.captain in ids and squad.captain not in bench:
                captain = squad.captain
            else:
                starters_by_price = sorted(
                    (pid for pid in ids if pid not in bench and pid in lookup),
                    key=lambda pid: lookup[pid].price,
                    reverse=True,
                )
                captain = starters_by_price[0] if starters_by_price else None

        players = []
        for pid in ids:
            p = lookup.get(pid)
            if p is None:
                continue
            players.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "team": p.team,
                    "position": p.position,
                    "price": p.price,
                    "status": p.status,
                    "team_code": p.team_code,
                    "slot": 12 + bench.index(pid) if pid in bench else 1,
                    "is_captain": pid == captain,
                    "is_vice": False,
                    "incoming": pid == s["transfer_in"],
                }
            )
        starters = [lookup[pid] for pid in ids if pid not in bench and pid in lookup]
        proposals[agent] = {
            "violations": (
                (["illegal bench"] if bench_fixed else [])
                + (["captain outside the starting squad"] if captain_fixed else [])
            ),
            "players": players,
            "bench_fixed": bench_fixed,
            "captain_fixed": captain_fixed,
            "formation": _formation(starters),
            "transfer_out": (lookup[s["transfer_out"]].name if s["transfer_out"] in lookup else s["transfer_out"]),
            "transfer_in": (lookup[s["transfer_in"]].name if s["transfer_in"] in lookup else s["transfer_in"]),
        }
    return proposals


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
                "has_xi": bool(snapshot.slots),
            }

    manual = load_manual_squad()
    if manual is not None:
        lookup = {p.id: p for p in fpl.get_players()}
        return {
            "squad": _squad_players(manual, lookup),
            "bank": manual.bank,
            "gw": None,
            "source": "manual",
            "has_xi": False,
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


VIOLATION_PENALTY = 2.0


def apply_violation_penalties(ledger, gw: int, proposals: dict) -> bool:
    changed = False
    for agent, prop in proposals.items():
        if prop.get("violations"):
            changed |= ledger.penalize(
                gw, agent, VIOLATION_PENALTY, " and ".join(prop["violations"])
            )
    return changed


@app.get("/api/scoreboard")
def scoreboard() -> dict:
    ledger = load_ledger()
    return {"scores": ledger.scores(), "history": ledger.history()}


@app.get("/api/debates")
def debates() -> dict:
    ledger = load_ledger()
    picks = {e["gw"]: e for e in ledger.history()}
    items = []
    if (MEMOS_DIR / "draft.md").exists():
        items.append({"name": "draft", "label": "Squad draft", "picked": None, "reward": None})
    for path in sorted(MEMOS_DIR.glob("gw*.md")):
        stem = path.stem
        if not stem[2:].isdigit():
            continue
        gw = int(stem[2:])
        entry = picks.get(gw)
        items.append(
            {
                "name": stem,
                "label": f"GW{gw}",
                "gw": gw,
                "picked": entry["picked"] if entry else None,
                "reward": entry["reward"] if entry else None,
            }
        )
    return {"debates": items}


@app.get("/api/debates/{name}")
def debate_detail(name: str) -> dict:
    if name != "draft" and not (name.startswith("gw") and name[2:].isdigit()):
        raise HTTPException(400, "name must be 'draft' or 'gw<N>'")
    memo_path = MEMOS_DIR / f"{name}.md"
    if not memo_path.exists():
        raise HTTPException(404, f"no saved debate called {name}")
    thread_path = MEMOS_DIR / f"{name}_thread.json"
    thread = (
        json.loads(thread_path.read_text(encoding="utf-8"))
        if thread_path.exists()
        else []
    )
    can_pick = False
    gw = None
    if name.startswith("gw"):
        gw = int(name[2:])
        ledger = load_ledger()
        already = any(e["gw"] == gw for e in ledger.history())
        can_pick = not already and (MEMOS_DIR / f"{name}_suggestions.json").exists()
    proposals_path = MEMOS_DIR / f"{name}_proposals.json"
    proposals = (
        json.loads(proposals_path.read_text(encoding="utf-8"))
        if proposals_path.exists()
        else {}
    )
    return {
        "memo": memo_path.read_text(encoding="utf-8"),
        "thread": thread,
        "agents": AGENTS,
        "gw": gw,
        "can_pick": can_pick,
        "proposals": proposals,
    }


def _do_draft() -> dict:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    result = run_draft_debate(client, players, ledger)

    MEMOS_DIR.mkdir(exist_ok=True)
    memo = render_draft_memo(result, ledger, players)
    thread = draft_thread(result, players)
    (MEMOS_DIR / "draft.md").write_text(memo, encoding="utf-8")
    (MEMOS_DIR / "draft_thread.json").write_text(
        json.dumps(thread, indent=2), encoding="utf-8"
    )
    return {"memo": memo, "thread": thread}


@app.post("/api/draft")
def draft() -> dict:
    return _start_job("draft", _do_draft)


def _do_memo(gw: int) -> dict:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    squad = get_squad_for_gw(fpl, gw)
    try:
        fixtures = fpl.get_team_fixtures()
    except httpx.HTTPError:
        fixtures = {}
    context = build_context(players, gw, squad=squad, fixtures=fixtures)
    context += elite_block_for_gw(fpl, gw, players, MEMOS_DIR, elite_n())
    context += build_debate_recap(gw, MEMOS_DIR, ledger)
    names_lookup = {p.id: p.name for p in players}
    histories = build_agent_histories(fpl, ledger, gw, MEMOS_DIR, names_lookup)
    result = run_debate(client, context, ledger, histories=histories)

    MEMOS_DIR.mkdir(exist_ok=True)
    names = {p.id: p.name for p in players}
    text = render_memo(result, ledger, gw, players=names)
    thread = debate_thread(result, names)
    (MEMOS_DIR / f"gw{gw}.md").write_text(text, encoding="utf-8")
    (MEMOS_DIR / f"gw{gw}_thread.json").write_text(
        json.dumps(thread, indent=2), encoding="utf-8"
    )
    suggestions = {agent: s.model_dump() for agent, s in result["final"].items()}
    (MEMOS_DIR / f"gw{gw}_suggestions.json").write_text(
        json.dumps(suggestions, indent=2), encoding="utf-8"
    )

    proposals = {}
    if squad is not None and squad.slots:
        lookup = {p.id: p for p in players}
        proposals = build_proposals(squad, lookup, suggestions)
        (MEMOS_DIR / f"gw{gw}_proposals.json").write_text(
            json.dumps(proposals, indent=2), encoding="utf-8"
        )
        if apply_violation_penalties(ledger, gw, proposals):
            ledger.save(LEDGER_PATH)

    return {"memo": text, "agents": AGENTS, "thread": thread, "proposals": proposals}


@app.post("/api/memo/{gw}")
def memo(gw: int) -> dict:
    return _start_job(f"memo-gw{gw}", lambda: _do_memo(gw))


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
