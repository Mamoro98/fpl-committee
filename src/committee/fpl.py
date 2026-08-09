import httpx
from pydantic import BaseModel

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


class Player(BaseModel):
    id: int
    name: str
    team: str
    position: str
    price: float
    form: float
    status: str


class FplClient:
    def _fetch_bootstrap(self) -> dict:
        response = httpx.get(BOOTSTRAP_URL, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_players(self) -> list[Player]:
        data = self._fetch_bootstrap()
        teams = {t["id"]: t["name"] for t in data["teams"]}
        positions = {e["id"]: e["singular_name_short"] for e in data["element_types"]}
        return [
            Player(
                id=p["id"],
                name=p["web_name"],
                team=teams[p["team"]],
                position=positions[p["element_type"]],
                price=p["now_cost"] / 10,
                form=float(p["form"]),
                status=p["status"],
            )
            for p in data["elements"]
        ]
