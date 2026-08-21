from typing import Literal

from pydantic import BaseModel, Field

from committee.fpl import Player
from committee.llm import Usage, sum_usage


class TransferMove(BaseModel):
    out_id: int
    in_id: int


class SquadProposal(BaseModel):
    squad: list[int]
    xi: list[int]
    captain: int
    vice_captain: int
    formation: str = ""
    rationale: str = ""
    transfers: list[TransferMove] = Field(default_factory=list)
    chip: str | None = None
    hits: int = 0


class Memo(BaseModel):
    model: str
    model_id: str
    role: Literal["member", "chair", "repair"]
    gameweek: int
    mode: Literal["pick", "week"]
    proposal: SquadProposal | None = None
    raw: str | None = None
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None


class Recommendation(BaseModel):
    gameweek: int
    mode: Literal["pick", "week"]
    squad_ids: list[int]
    xi: list[int]
    captain: int
    vice_captain: int
    formation: str
    budget_used: float
    bank: float
    transfers: list[TransferMove] = Field(default_factory=list)
    hits: int = 0
    chip: str | None = None
    locked_ids: list[int] = Field(default_factory=list)
    rationale: str = ""
    memos: list[Memo] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    errors: list[str] = Field(default_factory=list)

    def players(self, by_id: dict[int, Player]) -> list[Player]:
        return [by_id[i] for i in self.squad_ids if i in by_id]

    def refresh_usage(self) -> Usage:
        self.usage = sum_usage([m.usage for m in self.memos])
        return self.usage
