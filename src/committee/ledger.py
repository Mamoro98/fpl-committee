ALPHA = 0.15


class Ledger:
    def __init__(self, scores: dict[str, float], history: list[dict]):
        self._scores = scores
        self._history = history

    @classmethod
    def new(cls, agents: list[str], prior: float) -> "Ledger":
        return cls(scores={agent: prior for agent in agents}, history=[])

    def scores(self) -> dict[str, float]:
        return dict(self._scores)

    def record_pick(self, gw: int, agent: str) -> None:
        self._history.append({"gw": gw, "picked": agent, "reward": None})

    def settle(self, gw: int, reward: float) -> None:
        entry = next(e for e in self._history if e["gw"] == gw)
        entry["reward"] = reward
        picked = entry["picked"]
        self._scores[picked] = (1 - ALPHA) * self._scores[picked] + ALPHA * reward
