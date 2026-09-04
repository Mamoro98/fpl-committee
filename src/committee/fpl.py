import httpx
from pydantic import BaseModel

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
LIVE_URL = "https://fantasy.premierleague.com/api/event/{gw}/live/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/?future=1"
OVERALL_LEAGUE_URL = (
    "https://fantasy.premierleague.com/api/leagues-classic/314/standings/"
    "?page_standings={page}"
)
PICKS_URL = "https://fantasy.premierleague.com/api/entry/{entry_id}/event/{gw}/picks/"


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
    team_code: int = 0
    news: str = ""


class Squad(BaseModel):
    player_ids: list[int]
    bank: float
    slots: dict[int, int] = {}
    captain: int | None = None
    vice: int | None = None


class FplClient:
    def __init__(self):
        self._bootstrap: dict | None = None

    def _fetch_bootstrap(self) -> dict:
        if self._bootstrap is None:
            response = httpx.get(BOOTSTRAP_URL, timeout=30)
            response.raise_for_status()
            self._bootstrap = response.json()
        return self._bootstrap

    def _fetch_fixtures(self) -> list:
        response = httpx.get(FIXTURES_URL, timeout=30)
        response.raise_for_status()
        return response.json()

    def _fetch_standings_page(self, page: int) -> dict:
        response = httpx.get(OVERALL_LEAGUE_URL.format(page=page), timeout=30)
        response.raise_for_status()
        return response.json()

    def get_top_entries(self, n: int) -> list[int]:
        """Entry ids of the top n managers in the overall league, 50 per page."""
        entries: list[int] = []
        page = 1
        while len(entries) < n:
            data = self._fetch_standings_page(page)
            results = data["standings"]["results"]
            entries.extend(r["entry"] for r in results)
            if not data["standings"].get("has_next") or not results:
                break
            page += 1
        return entries[:n]

    def get_picks_raw(self, entry_id: int, gw: int) -> dict | None:
        try:
            return self._fetch_picks(entry_id, gw)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def get_team_fixtures(self, limit: int = 3) -> dict[str, list[str]]:
        """Per team: the next `limit` fixtures as 'GW3 BOU (H, diff 2)' strings."""
        data = self._fetch_bootstrap()
        short = {t["id"]: t["short_name"] for t in data["teams"]}
        full = {t["id"]: t["name"] for t in data["teams"]}
        out: dict[str, list[str]] = {name: [] for name in full.values()}
        for f in self._fetch_fixtures():
            if f.get("event") is None:
                continue
            home, away = f["team_h"], f["team_a"]
            if len(out[full[home]]) < limit:
                out[full[home]].append(
                    f"GW{f['event']} {short[away]} (H, diff {f['team_h_difficulty']})"
                )
            if len(out[full[away]]) < limit:
                out[full[away]].append(
                    f"GW{f['event']} {short[home]} (A, diff {f['team_a_difficulty']})"
                )
        return out

    def _fetch_live(self, gw: int) -> dict:
        response = httpx.get(LIVE_URL.format(gw=gw), timeout=30)
        response.raise_for_status()
        return response.json()

    def get_gw_points(self, gw: int) -> dict[int, int]:
        data = self._fetch_live(gw)
        return {e["id"]: e["stats"]["total_points"] for e in data["elements"]}

    def _fetch_picks(self, entry_id: int, gw: int) -> dict:
        response = httpx.get(PICKS_URL.format(entry_id=entry_id, gw=gw), timeout=30)
        response.raise_for_status()
        return response.json()

    def get_squad(self, entry_id: int, gw: int) -> "Squad | None":
        """Public squad snapshot after a GW is played. None if not available yet."""
        try:
            data = self._fetch_picks(entry_id, gw)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        captain = next((p["element"] for p in data["picks"] if p["is_captain"]), None)
        vice = next((p["element"] for p in data["picks"] if p["is_vice_captain"]), None)
        return Squad(
            player_ids=[p["element"] for p in data["picks"]],
            bank=data["entry_history"]["bank"] / 10,
            slots={p["element"]: p["position"] for p in data["picks"]},
            captain=captain,
            vice=vice,
        )

    def get_current_gw(self) -> int | None:
        """Latest gameweek with public data. None before the season starts."""
        data = self._fetch_bootstrap()
        current = [e["id"] for e in data["events"] if e.get("is_current")]
        if current:
            return current[0]
        finished = [e["id"] for e in data["events"] if e.get("finished")]
        return finished[-1] if finished else None

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
                team_code=p.get("team_code", 0),
                news=p.get("news") or "",
            )
            for p in data["elements"]
        ]
