import argparse
import json
from pathlib import Path

from committee.agents import AGENTS
from committee.debate import run_debate
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


def build_context(players, gw: int) -> str:
    top = sorted(players, key=lambda p: (p.form, p.price), reverse=True)[:40]
    lines = [
        f"id={p.id} {p.name} {p.team} {p.position} price={p.price} "
        f"form={p.form} status={p.status}"
        for p in top
    ]
    return (
        f"Gameweek {gw}. Recommend ONE transfer (out, in), a captain, and a bench "
        "order, using only players from this list:\n" + "\n".join(lines)
    )


def cmd_memo(args) -> None:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    context = build_context(players, args.gw)
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="committee")
    sub = parser.add_subparsers(dest="command", required=True)

    p_memo = sub.add_parser("memo", help="run the debate, write the weekly memo")
    p_memo.add_argument("--gw", type=int, required=True)
    p_memo.set_defaults(func=cmd_memo)

    p_pick = sub.add_parser("pick", help="record which agent you picked")
    p_pick.add_argument("agent", choices=AGENTS)
    p_pick.add_argument("--gw", type=int, required=True)
    p_pick.set_defaults(func=cmd_pick)

    p_settle = sub.add_parser("settle", help="apply real points to the picked agent")
    p_settle.add_argument("--gw", type=int, required=True)
    p_settle.set_defaults(func=cmd_settle)

    args = parser.parse_args(argv)
    args.func(args)
