import httpx
from pydantic import BaseModel

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
ENTRY_URL = "https://fantasy.premierleague.com/api/entry/{id}/"
PICKS_URL = "https://fantasy.premierleague.com/api/entry/{id}/event/{event}/picks/"


def _parse_float(value, default: float | None = 0.0) -> float | None:
    if value is None or value == "":
        return default
    return float(value)


class Player(BaseModel):
    id: int
    name: str
    team: str
    team_id: int
    team_short: str
    position: str
    price: float
    form: float
    status: str
    chance_of_playing_next_round: int | None = None
    selected_by_percent: float = 0.0
    ep_next: float | None = None
    news: str = ""


class Team(BaseModel):
    id: int
    name: str
    short_name: str
    strength_attack_home: int = 0
    strength_attack_away: int = 0
    strength_defence_home: int = 0
    strength_defence_away: int = 0


class Event(BaseModel):
    id: int
    name: str
    is_current: bool = False
    is_next: bool = False
    deadline_time: str | None = None
    finished: bool = False


class Fixture(BaseModel):
    event: int | None = None
    team_h: int
    team_a: int
    team_h_difficulty: int | None = None
    team_a_difficulty: int | None = None
    finished: bool = False
    kickoff_time: str | None = None


class Entry(BaseModel):
    id: int
    name: str
    current_event: int | None = None
    bank: float = 0.0
    squad_ids: list[int] = []
    xi_ids: list[int] = []
    captain_id: int | None = None
    vice_captain_id: int | None = None
    free_transfers: int = 1
    active_chip: str | None = None


class FplClient:
    def __init__(self, timeout: float = 30) -> None:
        self._timeout = timeout
        self._bootstrap: dict | None = None
        self._fixtures: list[dict] | None = None

    def _get_json(self, url: str) -> dict | list:
        response = httpx.get(url, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _fetch_bootstrap(self) -> dict:
        if self._bootstrap is None:
            data = self._get_json(BOOTSTRAP_URL)
            if not isinstance(data, dict):
                raise TypeError("bootstrap-static did not return an object")
            self._bootstrap = data
        return self._bootstrap

    def _fetch_fixtures(self) -> list[dict]:
        if self._fixtures is None:
            data = self._get_json(FIXTURES_URL)
            if not isinstance(data, list):
                raise TypeError("fixtures did not return a list")
            self._fixtures = data
        return self._fixtures

    def get_teams(self) -> list[Team]:
        return [
            Team(
                id=t["id"],
                name=t["name"],
                short_name=t.get("short_name", t["name"][:3]),
                strength_attack_home=t.get("strength_attack_home", 0),
                strength_attack_away=t.get("strength_attack_away", 0),
                strength_defence_home=t.get("strength_defence_home", 0),
                strength_defence_away=t.get("strength_defence_away", 0),
            )
            for t in self._fetch_bootstrap()["teams"]
        ]

    def get_players(self) -> list[Player]:
        data = self._fetch_bootstrap()
        teams = {
            t["id"]: (t["name"], t.get("short_name", t["name"][:3]))
            for t in data["teams"]
        }
        positions = {e["id"]: e["singular_name_short"] for e in data["element_types"]}
        players: list[Player] = []
        for p in data["elements"]:
            team_name, team_short = teams[p["team"]]
            chance = p.get("chance_of_playing_next_round")
            players.append(
                Player(
                    id=p["id"],
                    name=p["web_name"],
                    team=team_name,
                    team_id=p["team"],
                    team_short=team_short,
                    position=positions[p["element_type"]],
                    price=p["now_cost"] / 10,
                    form=_parse_float(p.get("form"), 0.0) or 0.0,
                    status=p.get("status", "a"),
                    chance_of_playing_next_round=chance,
                    selected_by_percent=_parse_float(p.get("selected_by_percent"), 0.0) or 0.0,
                    ep_next=_parse_float(p.get("ep_next"), None),
                    news=(p.get("news") or "")[:120],
                )
            )
        return players

    def get_events(self) -> list[Event]:
        return [
            Event(
                id=e["id"],
                name=e.get("name", f"Gameweek {e['id']}"),
                is_current=bool(e.get("is_current")),
                is_next=bool(e.get("is_next")),
                deadline_time=e.get("deadline_time"),
                finished=bool(e.get("finished")),
            )
            for e in self._fetch_bootstrap().get("events", [])
        ]

    def get_target_event(self) -> Event:
        events = self.get_events()
        if not events:
            raise RuntimeError("bootstrap-static contained no events")
        for event in events:
            if event.is_current:
                return event
        for event in events:
            if event.is_next:
                return event
        unfinished = [e for e in events if not e.finished]
        return unfinished[0] if unfinished else events[-1]

    def get_fixtures(self) -> list[Fixture]:
        return [
            Fixture(
                event=f.get("event"),
                team_h=f["team_h"],
                team_a=f["team_a"],
                team_h_difficulty=f.get("team_h_difficulty"),
                team_a_difficulty=f.get("team_a_difficulty"),
                finished=bool(f.get("finished")),
                kickoff_time=f.get("kickoff_time"),
            )
            for f in self._fetch_fixtures()
        ]

    def get_entry(self, team_id: int, free_transfers: int = 1) -> Entry:
        data = self._get_json(ENTRY_URL.format(id=team_id))
        if not isinstance(data, dict):
            raise TypeError("entry did not return an object")
        current_event = data.get("current_event")
        bank = (_parse_float(data.get("last_deadline_bank"), 0.0) or 0.0) / 10
        entry = Entry(
            id=data["id"],
            name=data.get("name", str(team_id)),
            current_event=current_event,
            bank=bank,
            free_transfers=free_transfers,
        )
        if current_event is None:
            return entry
        picks_data = self._get_json(PICKS_URL.format(id=team_id, event=current_event))
        if not isinstance(picks_data, dict):
            raise TypeError("picks did not return an object")
        picks = picks_data.get("picks") or []
        history = picks_data.get("entry_history") or {}
        if "bank" in history:
            entry.bank = (history["bank"] or 0) / 10
        entry.squad_ids = [p["element"] for p in picks]
        entry.xi_ids = [p["element"] for p in picks if p.get("position", 16) <= 11]
        entry.captain_id = next((p["element"] for p in picks if p.get("is_captain")), None)
        entry.vice_captain_id = next(
            (p["element"] for p in picks if p.get("is_vice_captain")), None
        )
        entry.active_chip = picks_data.get("active_chip")
        return entry
