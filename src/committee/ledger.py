import json
from pathlib import Path

ALPHA = 0.15


class Ledger:
    def __init__(
        self,
        scores: dict[str, float],
        history: list[dict],
        penalties: list[dict] | None = None,
    ):
        self._scores = scores
        self._history = history
        self._penalties = penalties or []

    @classmethod
    def new(cls, agents: list[str], prior: float) -> "Ledger":
        return cls(scores={agent: prior for agent in agents}, history=[])

    def scores(self) -> dict[str, float]:
        return dict(self._scores)

    def record_pick(self, gw: int, agent: str, suggestion: dict | None = None) -> None:
        self._history.append(
            {"gw": gw, "picked": agent, "reward": None, "suggestion": suggestion}
        )

    def settle(self, gw: int, reward: float) -> None:
        entry = next(e for e in self._history if e["gw"] == gw)
        entry["reward"] = reward
        picked = entry["picked"]
        self._scores[picked] = (1 - ALPHA) * self._scores[picked] + ALPHA * reward

    def history(self) -> list[dict]:
        return [dict(entry) for entry in self._history]

    def penalties(self) -> list[dict]:
        return [dict(entry) for entry in self._penalties]

    def penalize(self, gw: int, agent: str, amount: float, reason: str) -> bool:
        """Deduct reputation for a rule violation. Once per agent per GW."""
        if any(p["gw"] == gw and p["agent"] == agent for p in self._penalties):
            return False
        self._scores[agent] -= amount
        self._penalties.append(
            {"gw": gw, "agent": agent, "amount": amount, "reason": reason}
        )
        return True

    def save(self, path: Path) -> None:
        data = {
            "scores": self._scores,
            "history": self._history,
            "penalties": self._penalties,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            scores=data["scores"],
            history=data["history"],
            penalties=data.get("penalties", []),
        )
