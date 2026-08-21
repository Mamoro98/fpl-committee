from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

from committee.assemble import assemble_proposal
from committee.config import Settings
from committee.fpl import Event, FplClient, Player
from committee.llm import ChatClient, ChatError, Usage, extract_json, sum_usage
from committee.pack import build_pack
from committee.schema import Memo, Recommendation, SquadProposal, TransferMove
from committee.validate import budget_used, formation_from_xi, legal_locks, validate_squad

RULES = """FPL hard rules:
- 15 players: 2 GKP, 5 DEF, 5 MID, 3 FWD
- Max 3 players from any club
- XI: 1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD; exactly 11 unique ids from the squad
- Captain and vice-captain must be different players in the XI
- Use only player ids from the provided table
- Prices are the £ column; do not exceed the stated budget

Return ONLY a JSON object with:
{
  "squad": [15 ints],
  "xi": [11 ints],
  "captain": int,
  "vice_captain": int,
  "formation": "3-4-3",
  "rationale": "short",
  "transfers": [{"out_id": int, "in_id": int}],
  "chip": null,
  "hits": 0
}
chip may be null, "wildcard", "freehit", "bboost", or "3xc".
hits = max(0, transfers - free_transfers) * 4, or 0 if chip is wildcard/freehit.
For a from-scratch squad, transfers must be [] and hits 0.
"""

JSON_SYSTEM = (
    "Reply with one JSON object only. The first character must be '{'. "
    "No preamble, no analysis, no markdown fences."
)


def parse_proposal(text: str) -> SquadProposal:
    data = extract_json(text)
    transfers: list[TransferMove] = []
    for item in data.get("transfers") or []:
        if not isinstance(item, dict):
            continue
        out_id = item.get("out_id", item.get("out"))
        in_id = item.get("in_id", item.get("in"))
        if out_id is None or in_id is None:
            continue
        transfers.append(TransferMove(out_id=int(out_id), in_id=int(in_id)))
    chip = data.get("chip")
    if chip in {"", "none", "null"}:
        chip = None
    vice = data.get("vice_captain", data.get("vice"))
    return SquadProposal(
        squad=[int(x) for x in data["squad"]],
        xi=[int(x) for x in data["xi"]],
        captain=int(data["captain"]),
        vice_captain=int(vice),
        formation=str(data.get("formation") or ""),
        rationale=str(data.get("rationale") or ""),
        transfers=transfers,
        chip=chip,
        hits=int(data.get("hits") or 0),
    )


def _format_squad_lines(ids: list[int], players_by_id: dict[int, Player]) -> str:
    lines = []
    for pid in ids:
        player = players_by_id.get(pid)
        if player is None:
            lines.append(f"{pid} UNKNOWN")
            continue
        lines.append(
            f"{player.id} {player.name} {player.position} {player.team_short} {player.price:.1f}"
        )
    return "\n".join(lines)


class Committee:
    def __init__(self, chat: ChatClient, settings: Settings, client: FplClient | None = None) -> None:
        self.chat = chat
        self.settings = settings
        self.client = client or FplClient()

    def pick(self) -> Recommendation:
        players = self.client.get_players()
        teams = self.client.get_teams()
        fixtures = self.client.get_fixtures()
        event = self.client.get_target_event()
        pack = build_pack(players, teams, fixtures, event)
        budget = 100.0
        extra = f"Build a new 15-man squad. Budget is £{budget:.1f}m. transfers must be []."
        return self._run("pick", event, players, pack, budget=budget, extra=extra)

    def week(self, team_id: int, free_transfers: int = 1) -> Recommendation:
        players = self.client.get_players()
        teams = self.client.get_teams()
        fixtures = self.client.get_fixtures()
        event = self.client.get_target_event()
        entry = self.client.get_entry(team_id, free_transfers=free_transfers)
        if not entry.squad_ids:
            raise RuntimeError(
                "No public picks for this team yet. Use `pick` to build a GW1 squad, "
                "or wait until the team has been entered."
            )
        pack = build_pack(players, teams, fixtures, event, extra_ids=entry.squad_ids)
        by_id = {p.id: p for p in players}
        current_cost = budget_used([by_id[i] for i in entry.squad_ids if i in by_id])
        budget = current_cost + entry.bank
        pack += (
            f"\nCurrent squad (sell/buy approximated at listed price). "
            f"Bank £{entry.bank:.1f}m. Free transfers: {entry.free_transfers}. "
            f"Effective budget for the new 15: £{budget:.1f}m.\n"
            f"{_format_squad_lines(entry.squad_ids, by_id)}"
        )
        extra = (
            f"Start from the current squad. You may make 0-3 transfers. "
            f"{entry.free_transfers} free transfer(s); extras cost -4 hits each. "
            f"Keep hits honest. Do not recommend auto-submitting."
        )
        return self._run(
            "week",
            event,
            players,
            pack,
            budget=budget,
            extra=extra,
            current_squad=entry.squad_ids,
            free_transfers=entry.free_transfers,
        )

    def _run(
        self,
        mode: str,
        event: Event,
        players: list[Player],
        pack: str,
        *,
        budget: float,
        extra: str,
        current_squad: list[int] | None = None,
        free_transfers: int = 1,
    ) -> Recommendation:
        by_id = {p.id: p for p in players}
        budget_tenths = round(budget * 10)
        roster = self.settings.members()
        member_prompt = (
            f"You are a Fantasy Premier League expert on a {len(roster)}-model committee.\n"
            f"Target {event.name}. {extra}\n\n{RULES}\n\nPlayer table:\n{pack}"
        )
        memos: list[Memo] = []
        with ThreadPoolExecutor(max_workers=len(roster) or 1) as pool:
            futures = {
                pool.submit(
                    self._ask,
                    model_id,
                    [
                        {"role": "system", "content": JSON_SYSTEM},
                        {"role": "user", "content": member_prompt},
                    ],
                ): (name, model_id)
                for name, model_id in roster
            }
            for future in as_completed(futures):
                name, model_id = futures[future]
                try:
                    proposal, raw, usage, error = future.result()
                except Exception as exc:
                    proposal, raw, usage, error = None, None, Usage(), str(exc)
                memos.append(
                    Memo(
                        model=name,
                        model_id=model_id,
                        role="member",
                        gameweek=event.id,
                        mode=mode,  # type: ignore[arg-type]
                        proposal=proposal,
                        raw=raw,
                        usage=usage,
                        error=error,
                    )
                )

        votes: Counter[int] = Counter()
        captain_votes: Counter[int] = Counter()
        for memo in memos:
            if memo.proposal is None:
                continue
            votes.update(memo.proposal.squad)
            captain_votes[memo.proposal.captain] += 1

        errors: list[str] = []
        locked: list[int] = []
        proposal: SquadProposal | None = None
        try:
            locked = legal_locks(votes, by_id)
            proposal = assemble_proposal(
                locked,
                players,
                votes,
                captain_votes,
                budget_tenths,
                current_squad=current_squad,
                free_transfers=free_transfers,
            )
        except Exception as exc:
            errors.append(f"chair failed: {exc}")
        else:
            memos.append(
                Memo(
                    model="greedy",
                    model_id="code",
                    role="chair",
                    gameweek=event.id,
                    mode=mode,  # type: ignore[arg-type]
                    proposal=proposal,
                    usage=Usage(),
                )
            )
            errors.extend(
                validate_squad(
                    proposal,
                    by_id,
                    budget_tenths=budget_tenths,
                    current_squad=current_squad,
                    free_transfers=free_transfers,
                )
            )

        return self._recommendation(
            event,
            mode,
            proposal,
            memos,
            errors,
            by_id,
            budget_tenths,
            locked,
        )

    def _recommendation(
        self,
        event: Event,
        mode: str,
        proposal: SquadProposal | None,
        memos: list[Memo],
        errors: list[str],
        by_id: dict[int, Player],
        budget_tenths: int,
        locked: list[int],
    ) -> Recommendation:
        usage = sum_usage([m.usage for m in memos])
        if proposal is None:
            return Recommendation(
                gameweek=event.id,
                mode=mode,  # type: ignore[arg-type]
                squad_ids=[],
                xi=[],
                captain=0,
                vice_captain=0,
                formation="",
                budget_used=0.0,
                bank=round(budget_tenths / 10, 1),
                locked_ids=locked,
                memos=memos,
                usage=usage,
                errors=errors or ["committee produced no squad"],
            )
        squad_players = [by_id[i] for i in proposal.squad if i in by_id]
        xi_players = [by_id[i] for i in proposal.xi if i in by_id]
        used = budget_used(squad_players)
        formation = proposal.formation or formation_from_xi(xi_players)
        bank = (budget_tenths / 10) - used
        return Recommendation(
            gameweek=event.id,
            mode=mode,  # type: ignore[arg-type]
            squad_ids=proposal.squad,
            xi=proposal.xi,
            captain=proposal.captain,
            vice_captain=proposal.vice_captain,
            formation=formation,
            budget_used=used,
            bank=round(bank, 1),
            transfers=proposal.transfers,
            hits=proposal.hits,
            chip=proposal.chip,
            locked_ids=locked,
            rationale=proposal.rationale,
            memos=memos,
            usage=usage,
            errors=errors,
        )

    def _ask(
        self, model_id: str, messages: list[dict]
    ) -> tuple[SquadProposal | None, str | None, Usage, str | None]:
        print(f"asking {model_id}...", file=sys.stderr, flush=True)
        try:
            result = self.chat.complete(model_id, messages, max_tokens=self.settings.max_tokens)
        except ChatError as exc:
            return None, exc.content or None, exc.usage, str(exc)
        except Exception as exc:
            return None, None, Usage(), str(exc)
        try:
            return parse_proposal(result.content), result.content, result.usage, None
        except Exception as exc:
            return None, result.content, result.usage, str(exc)
