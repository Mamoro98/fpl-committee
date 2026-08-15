import httpx
from pydantic import BaseModel

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
LIVE_URL = "https://fantasy.premierleague.com/api/event/{gw}/live/"


class Player(BaseModel):
    id: int
    name: str
    team: str
    position: str
    price: float
    form: float
    status: str
    ownership: float
    total_points: int


class FplClient:
    def _fetch_bootstrap(self) -> dict:
        response = httpx.get(BOOTSTRAP_URL, timeout=30)
        response.raise_for_status()
        return response.json()

    def _fetch_live(self, gw: int) -> dict:
        response = httpx.get(LIVE_URL.format(gw=gw), timeout=30)
        response.raise_for_status()
        return response.json()

    def get_gw_points(self, gw: int) -> dict[int, int]:
        data = self._fetch_live(gw)
        return {e["id"]: e["stats"]["total_points"] for e in data["elements"]}

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
                ownership=float(p["selected_by_percent"]),
                total_points=p["total_points"],
            )
            for p in data["elements"]
        ]
