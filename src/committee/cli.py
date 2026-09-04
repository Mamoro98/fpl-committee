import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from committee.agents import AGENTS, CHIPS, suggestion_dict
from committee.debate import run_debate
from committee.draft import run_draft_debate
from committee.draft_memo import render_draft_memo
from committee.elite import (
    DEFAULT_N,
    build_elite_snapshot,
    elite_block_for_gw,
    render_elite_block,
    save_elite_snapshot,
)
from committee.fpl import FplClient
from committee.history import build_agent_histories, build_debate_recap
from committee.ledger import Ledger
from committee.llm import LlmClient
from committee.match_model import match_model_block_for_gw
from committee.memo import debate_thread, render_memo
from committee.reward import compute_reward

LEDGER_PATH = Path("ledger.json")
MEMOS_DIR = Path("memos")
PRIOR = 17.0


def load_ledger() -> Ledger:
    if LEDGER_PATH.exists():
        return Ledger.load(LEDGER_PATH)
    return Ledger.new(agents=AGENTS, prior=PRIOR)


DIFFERENTIAL_OWNERSHIP = 10.0


def elite_n() -> int:
    return int(os.environ.get("ELITE_N", DEFAULT_N))


def free_transfers() -> int:
    return int(os.environ.get("FREE_TRANSFERS", "1"))


def build_manager_block(fpl, gw: int) -> str:
    """Free transfers, hit cost, and chips still available to the manager."""
    entry_id = os.environ.get("FPL_ENTRY_ID")
    used: list[str] = []
    if entry_id:
        try:
            used = fpl.get_chips_used(int(entry_id))
        except httpx.HTTPError:
            used = []
    available = [c for c in CHIPS if c not in used]
    ft = free_transfers()
    return (
        f"\n\nMANAGER STATUS: {ft} free transfer(s) this week. Every transfer beyond "
        "that costs 4 points. Recommend extra transfers ONLY when the expected extra "
        "points over the next 3 gameweeks clearly beat 4 per extra transfer, and say "
        f"so in the rationale. Chips still available: {', '.join(available) or 'none'}. "
        "wildcard = unlimited free transfers this week (send the full list of "
        "transfers); freehit = unlimited transfers for one week only, squad reverts "
        "after; bboost = bench points count this week; 3xc = captain scores triple. "
        "Use a chip only when the gain is large and obvious, chips are once per season."
    )


def get_squad_for_gw(fpl: FplClient, gw: int):
    from committee.manual import load_manual_squad

    entry_id = os.environ.get("FPL_ENTRY_ID")
    if entry_id and gw > 1:
        squad = fpl.get_squad(int(entry_id), gw - 1)
        if squad is not None:
            return squad
    return load_manual_squad()


def price_trend(p) -> str:
    """Compact price signal: this week's change and net transfers driving the next one."""
    net = getattr(p, "net_transfers_week", 0)
    change = getattr(p, "price_change_week", 0.0)
    if not net and not change:
        return ""
    net_k = f"{net / 1000:+.0f}k"
    direction = "FALLING" if net < -50_000 else ("RISING" if net > 50_000 else "steady")
    return f" price_change_wk={change:+.1f} net_transfers={net_k} ({direction})"


def build_context(players, gw: int, squad=None, fixtures=None) -> str:
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
        news = f" news={p.news[:70]}" if getattr(p, "news", "") else ""
        trend = price_trend(p)
        return (
            f"id={p.id} {p.name} {p.team} {p.position} price={p.price} "
            f"form={p.form} points={p.total_points} owned={p.ownership}% "
            f"status={p.status}{trend}{news}"
        )

    lines = [player_line(p) for p in picked]
    lookup = {p.id: p for p in players}

    squad_block = ""
    if squad is not None:
        squad_lines = [
            player_line(lookup[pid]) for pid in squad.player_ids if pid in lookup
        ]
        squad_block = (
            "\n\nMY CURRENT SQUAD (transfer_out MUST be one of these ids, and "
            f"transfer_in price must fit bank {squad.bank}m plus the sold "
            "player's price):\n" + "\n".join(squad_lines)
        )

    fixture_block = ""
    if fixtures:
        relevant = {p.team for p in picked}
        if squad is not None:
            relevant |= {lookup[pid].team for pid in squad.player_ids if pid in lookup}
        fixture_lines = [
            f"{team}: {', '.join(fixtures[team])}"
            for team in sorted(relevant)
            if fixtures.get(team)
        ]
        fixture_block = (
            "\n\nUPCOMING FIXTURES (H=home, A=away, diff 1=easiest to 5=hardest):\n"
            + "\n".join(fixture_lines)
        )

    return (
        f"Gameweek {gw}. Recommend the transfers (usually one), a captain, and a bench "
        "order, using only players from this list. Low owned= values are "
        "differentials. Prices move with net transfers: a FALLING player loses "
        "0.1m soon (sell before the drop keeps the money), a RISING one costs "
        "more next week (buy before the rise).\n"
        + "\n".join(lines)
        + squad_block
        + fixture_block
        + '\n\nRespond with ONE JSON object only:\n{"transfers": [{"out": <player id>, '
        '"in": <player id>}, ...], "chip": null or "wildcard"/"freehit"/"bboost"/"3xc", '
        '"captain": <player id>, "bench_order": [<4 player ids>], "rationale": '
        '"<max 80 words>", "attacks": ["<round 2 only: specific criticism of a '
        'rival claim>"]}\n'
        "transfers rules: one transfer is the default; every out id must be in my "
        "squad, every in id must not be, and total in prices must fit bank plus "
        "total out prices. "
        "bench_order rules: exactly 4 ids from my squad after your transfers, "
        "EXACTLY ONE goalkeeper among them (the other keeper starts), and the "
        "remaining eleven must keep at least 3 DEF and at least 1 FWD. "
        "captain rules: the captain id MUST be a player in my squad after your "
        "transfer and MUST be in the starting eleven, never on the bench."
    )


def cmd_memo(args) -> None:
    fpl = FplClient()
    client = LlmClient()
    ledger = load_ledger()
    players = fpl.get_players()
    squad = get_squad_for_gw(fpl, args.gw)
    try:
        fixtures = fpl.get_team_fixtures()
    except httpx.HTTPError:
        fixtures = {}
    context = build_context(players, args.gw, squad=squad, fixtures=fixtures)
    context += elite_block_for_gw(fpl, args.gw, players, MEMOS_DIR, elite_n())
    try:
        context += match_model_block_for_gw(fpl, args.gw)
    except httpx.HTTPError:
        pass
    context += build_manager_block(fpl, args.gw)
    context += build_debate_recap(args.gw, MEMOS_DIR, ledger)
    names_lookup = {p.id: p.name for p in players}
    histories = build_agent_histories(fpl, ledger, args.gw, MEMOS_DIR, names_lookup)
    result = run_debate(client, context, ledger, histories=histories)

    MEMOS_DIR.mkdir(exist_ok=True)
    names = {p.id: p.name for p in players}
    memo = render_memo(result, ledger, args.gw, players=names)
    (MEMOS_DIR / f"gw{args.gw}.md").write_text(memo, encoding="utf-8")
    (MEMOS_DIR / f"gw{args.gw}_thread.json").write_text(
        json.dumps(debate_thread(result, names), indent=2), encoding="utf-8"
    )
    suggestions = {agent: suggestion_dict(s) for agent, s in result["final"].items()}
    (MEMOS_DIR / f"gw{args.gw}_suggestions.json").write_text(
        json.dumps(suggestions, indent=2), encoding="utf-8"
    )
    if squad is not None and squad.slots:
        from committee.web import apply_violation_penalties, build_proposals

        lookup = {p.id: p for p in players}
        proposals = build_proposals(squad, lookup, suggestions)
        (MEMOS_DIR / f"gw{args.gw}_proposals.json").write_text(
            json.dumps(proposals, indent=2), encoding="utf-8"
        )
        if apply_violation_penalties(ledger, args.gw, proposals):
            ledger.save(LEDGER_PATH)
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
    reward, breakdown = compute_reward(suggestion, points, free_transfers())
    ledger.settle(gw=args.gw, reward=reward)
    ledger.save(LEDGER_PATH)

    print(f"GW{args.gw}: {entry['picked']} rewarded {reward:.1f} {breakdown}")
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
    ledger.save(LEDGER_PATH)
    print(memo)


def cmd_fine(args) -> None:
    """Manager's discretionary fine: reputation deducted, reason shown to the agent."""
    ledger = load_ledger()
    targets = AGENTS if args.agent == "all" else [args.agent]
    for agent in targets:
        applied = ledger.penalize(args.gw, agent, args.amount, args.reason)
        state = "fined" if applied else "already fined this GW, skipped"
        print(f"{agent}: {state}")
    ledger.save(LEDGER_PATH)
    for agent, score in sorted(ledger.scores().items(), key=lambda kv: -kv[1]):
        print(f"{agent}: {score:.2f}")


def cmd_elite(args) -> None:
    fpl = FplClient()
    snapshot = build_elite_snapshot(fpl, args.gw, args.n)
    save_elite_snapshot(snapshot, MEMOS_DIR)
    print(render_elite_block(snapshot, fpl.get_players()))


def cmd_web(args) -> None:
    import uvicorn

    uvicorn.run("committee.web:app", host="127.0.0.1", port=args.port)


def main(argv=None) -> None:
    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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

    p_fine = sub.add_parser("fine", help="deduct reputation from an agent (or all) with a reason")
    p_fine.add_argument("agent", choices=[*AGENTS, "all"])
    p_fine.add_argument("--gw", type=int, required=True)
    p_fine.add_argument("--amount", type=float, default=1.0)
    p_fine.add_argument("--reason", required=True)
    p_fine.set_defaults(func=cmd_fine)

    p_elite = sub.add_parser("elite", help="snapshot the top managers' squads for a GW")
    p_elite.add_argument("--gw", type=int, required=True, help="a finished gameweek")
    p_elite.add_argument("--n", type=int, default=elite_n())
    p_elite.set_defaults(func=cmd_elite)

    p_web = sub.add_parser("web", help="serve the dashboard on localhost")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    args.func(args)
