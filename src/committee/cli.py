from __future__ import annotations

import argparse
import sys
from pathlib import Path

from committee.config import Settings
from committee.fpl import FplClient, Player
from committee.llm import OpenRouterClient, Usage
from committee.run import Committee
from committee.schema import Recommendation
from committee.storage import append_ledger, save_memo

POSITION_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}


def format_usd(amount: float) -> str:
    if amount == 0:
        return "$0"
    if amount < 0.01:
        return f"${amount:.6f}"
    return f"${amount:.4f}"


def format_usage(rec: Recommendation) -> str:
    lines = ["Usage"]
    for memo in rec.memos:
        lines.append(_usage_line(f"{memo.role}/{memo.model}", memo.usage, memo.error))
    lines.append(_usage_line("total", rec.usage))
    return "\n".join(lines)


def _usage_line(label: str, usage: Usage, error: str | None = None) -> str:
    line = (
        f"  {label:22}  in {usage.prompt_tokens:>7}  "
        f"out {usage.completion_tokens:>7}  {format_usd(usage.cost_usd)}"
    )
    if error:
        snippet = error.replace("\n", " ").strip()[:80]
        line += f"  FAILED: {snippet}"
    return line


def format_recommendation(rec: Recommendation, players: list[Player]) -> str:
    by_id = {p.id: p for p in players}
    locked = set(rec.locked_ids)
    lines = [
        f"Gameweek {rec.gameweek} ({rec.mode})",
        f"Budget used £{rec.budget_used:.1f}m  bank £{rec.bank:.1f}m  "
        f"formation {rec.formation}  hits -{rec.hits}"
        + (f"  chip {rec.chip}" if rec.chip else ""),
    ]
    cap = by_id.get(rec.captain)
    vice = by_id.get(rec.vice_captain)
    lines.append(
        f"Captain: {cap.name if cap else rec.captain}    "
        f"Vice: {vice.name if vice else rec.vice_captain}"
    )
    if rec.transfers:
        lines.append("Transfers:")
        for move in rec.transfers:
            out_p = by_id.get(move.out_id)
            in_p = by_id.get(move.in_id)
            out_s = f"{out_p.name} ({out_p.team_short})" if out_p else str(move.out_id)
            in_s = f"{in_p.name} ({in_p.team_short})" if in_p else str(move.in_id)
            lines.append(f"  {out_s} -> {in_s}")
    lines.append("")
    squad = [by_id[i] for i in rec.squad_ids if i in by_id]
    squad.sort(key=lambda p: (POSITION_ORDER.get(p.position, 9), -p.price, p.id))
    xi = set(rec.xi)
    current_pos = None
    for player in squad:
        if player.position != current_pos:
            current_pos = player.position
            lines.append(current_pos)
        marks = []
        if player.id == rec.captain:
            marks.append("C")
        if player.id == rec.vice_captain:
            marks.append("VC")
        if player.id not in xi:
            marks.append("bench")
        if player.id in locked:
            marks.append("lock")
        suffix = f"  [{', '.join(marks)}]" if marks else ""
        lines.append(
            f"  {player.name:16} {player.team_short:3} £{player.price:4.1f}  "
            f"form {player.form:.1f}{suffix}"
        )
    if rec.rationale:
        lines.append("")
        lines.append(rec.rationale)
    if rec.errors:
        lines.append("")
        lines.append("Errors")
        for err in rec.errors:
            lines.append(f"  {err}")
    lines.append("")
    lines.append(format_usage(rec))
    lines.append("")
    lines.append("Enter this on the FPL site yourself; this tool does not submit picks.")
    return "\n".join(lines)


def _persist(rec: Recommendation, memos_dir: Path, ledger: Path) -> None:
    for memo in rec.memos:
        save_memo(memos_dir, memo)
    append_ledger(ledger, rec)


def build_committee(settings: Settings | None = None) -> tuple[Committee, Settings]:
    settings = settings or Settings.from_env()
    chat = OpenRouterClient(settings.api_key)
    return Committee(chat, settings, FplClient()), settings


def _finish(rec: Recommendation, players: list[Player], args: argparse.Namespace) -> int:
    _persist(rec, Path(args.memos_dir), Path(args.ledger))
    print(format_recommendation(rec, players))
    if rec.errors:
        print("error: " + "; ".join(rec.errors), file=sys.stderr)
        return 1
    return 0


def cmd_pick(args: argparse.Namespace) -> int:
    committee, _ = build_committee()
    rec = committee.pick()
    return _finish(rec, committee.client.get_players(), args)


def cmd_week(args: argparse.Namespace) -> int:
    committee, _ = build_committee()
    rec = committee.week(args.team_id, free_transfers=args.free_transfers)
    return _finish(rec, committee.client.get_players(), args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fpl-committee",
        description="Committee of OpenRouter models that proposes an FPL squad or weekly transfers.",
    )
    parser.add_argument("--memos-dir", default="memos")
    parser.add_argument("--ledger", default="ledger.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pick = sub.add_parser("pick", help="Build a 15-man squad from scratch")
    pick.set_defaults(func=cmd_pick)

    week = sub.add_parser("week", help="Recommend transfers from a public FPL team id")
    week.add_argument("--team-id", type=int, required=True)
    week.add_argument("--free-transfers", type=int, default=1)
    week.set_defaults(func=cmd_week)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
