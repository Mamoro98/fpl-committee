import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from committee.agents import AGENTS
from committee.debate import run_debate
from committee.draft import run_draft_debate
from committee.draft_memo import render_draft_memo
from committee.fpl import FplClient
from committee.ledger import Ledger
from committee.llm import LlmClient
from committee.memo import render_memo

LEDGER_PATH = Path("ledger.json")
MEMOS_DIR = Path("memos")
PRIOR = 17.0


def load_ledger() -> Ledger:
    if LEDGER_PATH.exists():
        return Ledger.load(LEDGER_PATH)
    return Ledger.new(agents=AGENTS, prior=PRIOR)


DIFFERENTIAL_OWNERSHIP = 10.0


def get_squad_for_gw(fpl: FplClient, gw: int):
    from committee.manual import load_manual_squad

    entry_id = os.environ.get("FPL_ENTRY_ID")
    if entry_id and gw > 1:
        squad = fpl.get_squad(int(entry_id), gw - 1)
        if squad is not None:
            return squad
    return load_manual_squad()


def build_context(players, gw: int, squad=None) -> str:
    hot = sorted(players, key=lambda p: p.form, reverse=True)[:20]
    value = sorted(
        players,
        key=lambda p: p.total_points / p.price if p.price else 0,
        reverse=True,
    )[:10]
    low_owned = [p for p in players if p.ownership < DIFFERENTIAL_OWNERSHIP]
    differentials = sorted(low_owned, key=lambda p: p.form, reverse=True)[:10]

    seen: set[int] = set()
    picked = []
    for p in [*hot, *value, *differentials]:
        if p.id not in seen:
            seen.add(p.id)
            picked.append(p)

    def player_line(p):
        return (
            f"id={p.id} {p.name} {p.team} {p.position} price={p.price} "
            f"form={p.form} points={p.total_points} owned={p.ownership}% "
            f"status={p.status}"
        )

    lines = [player_line(p) for p in picked]

    squad_block = ""
    if squad is not None:
        lookup = {p.id: p for p in players}
        squad_lines = [
            player_line(lookup[pid]) for pid in squad.player_ids if pid in lookup
        ]
        squad_block = (
            "\n\nMY CURRENT SQUAD (transfer_out MUST be one of these ids, and "
            f"transfer_in price must fit bank {squad.bank}m plus the sold "
            "player's price):\n" + "\n".join(squad_lines)
        )

    return (
        f"Gameweek {gw}. Recommend ONE transfer (out, in), a captain, and a bench "
        "order, using only players from this list. Low owned= values are "
        "differentials.\n"
        + "\n".join(lines)
        + squad_block
        + '\n\nRespond with ONE JSON object only:\n{"transfer_in": <player id>, '
        '"transfer_out": <player id>, "captain": <player id>, "bench_order": '
        '[<player ids>], "rationale": "<max 80 words>", "attacks": '
        '["<round 2 only: specific criticism of a rival claim>"]}'
    )


def cmd_memo(args) -> None:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    squad = get_squad_for_gw(fpl, args.gw)
    context = build_context(players, args.gw, squad=squad)
    result = run_debate(client, context, ledger)

    MEMOS_DIR.mkdir(exist_ok=True)
    names = {p.id: p.name for p in players}
    memo = render_memo(result, ledger, args.gw, players=names)
    (MEMOS_DIR / f"gw{args.gw}.md").write_text(memo, encoding="utf-8")
    (MEMOS_DIR / f"gw{args.gw}_suggestions.json").write_text(
        json.dumps(
            {agent: s.model_dump() for agent, s in result["final"].items()}, indent=2
        ),
        encoding="utf-8",
    )
    print(memo)


def cmd_pick(args) -> None:
    suggestions_path = MEMOS_DIR / f"gw{args.gw}_suggestions.json"
    if not suggestions_path.exists():
        raise SystemExit(f"no memo for GW{args.gw}, run: committee memo --gw {args.gw}")
    suggestions = json.loads(suggestions_path.read_text(encoding="utf-8"))
    if args.agent not in suggestions:
        raise SystemExit(f"unknown agent {args.agent!r}, options: {', '.join(suggestions)}")

    ledger = load_ledger()
    ledger.record_pick(gw=args.gw, agent=args.agent, suggestion=suggestions[args.agent])
    ledger.save(LEDGER_PATH)
    print(f"GW{args.gw}: picked {args.agent}")


def cmd_settle(args) -> None:
    ledger = load_ledger()
    entry = next((e for e in ledger.history() if e["gw"] == args.gw), None)
    if entry is None:
        raise SystemExit(f"no pick recorded for GW{args.gw}")
    suggestion = entry["suggestion"]

    points = FplClient().get_gw_points(args.gw)
    reward = float(
        10
        + points.get(suggestion["transfer_in"], 0)
        + points.get(suggestion["captain"], 0)
    )
    ledger.settle(gw=args.gw, reward=reward)
    ledger.save(LEDGER_PATH)

    print(f"GW{args.gw}: {entry['picked']} rewarded {reward:.1f}")
    for agent, score in sorted(ledger.scores().items(), key=lambda kv: -kv[1]):
        print(f"{agent}: {score:.2f}")


def cmd_draft(args) -> None:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    result = run_draft_debate(client, players, ledger)

    MEMOS_DIR.mkdir(exist_ok=True)
    memo = render_draft_memo(result, ledger, players)
    (MEMOS_DIR / "draft.md").write_text(memo, encoding="utf-8")
    print(memo)


def cmd_web(args) -> None:
    import uvicorn

    uvicorn.run("committee.web:app", host="127.0.0.1", port=args.port)


def main(argv=None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="committee")
    sub = parser.add_subparsers(dest="command", required=True)

    p_memo = sub.add_parser("memo", help="run the debate, write the weekly memo")
    p_memo.add_argument("--gw", type=int, required=True)
    p_memo.set_defaults(func=cmd_memo)

    p_pick = sub.add_parser("pick", help="record which agent you picked")
    p_pick.add_argument("agent", choices=AGENTS)
    p_pick.add_argument("--gw", type=int, required=True)
    p_pick.set_defaults(func=cmd_pick)

    p_draft = sub.add_parser("draft", help="one-off debate: full GW1 squad + formation")
    p_draft.set_defaults(func=cmd_draft)

    p_settle = sub.add_parser("settle", help="apply real points to the picked agent")
    p_settle.add_argument("--gw", type=int, required=True)
    p_settle.set_defaults(func=cmd_settle)

    p_web = sub.add_parser("web", help="serve the dashboard on localhost")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    args.func(args)
