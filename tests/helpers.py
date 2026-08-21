from committee.fpl import Event, Player, Team

TEAMS = [
    Team(id=1, name="Arsenal", short_name="ARS", strength_attack_home=1300),
    Team(id=2, name="Brighton", short_name="BHA"),
    Team(id=3, name="Liverpool", short_name="LIV"),
    Team(id=4, name="Chelsea", short_name="CHE"),
    Team(id=5, name="Fulham", short_name="FUL"),
    Team(id=6, name="Crystal Palace", short_name="CRY"),
    Team(id=7, name="Brentford", short_name="BRE"),
    Team(id=8, name="Bournemouth", short_name="BOU"),
    Team(id=9, name="Man City", short_name="MCI", strength_attack_home=1360),
    Team(id=10, name="Aston Villa", short_name="AVL"),
    Team(id=11, name="Wolves", short_name="WOL"),
    Team(id=12, name="Nott'm Forest", short_name="NFO"),
    Team(id=13, name="West Ham", short_name="WHU"),
]

# Legal 15 (ids 1-15) sums to £100.0m, max 3 per club.
_SPECS = [
    (1, "Raya", "GKP", 1, 5.0),
    (2, "Steele", "GKP", 2, 4.5),
    (3, "Gabriel", "DEF", 1, 6.0),
    (4, "Van Dijk", "DEF", 3, 5.0),
    (5, "Colwill", "DEF", 4, 4.5),
    (6, "Robinson", "DEF", 5, 4.5),
    (7, "Guehi", "DEF", 6, 4.5),
    (8, "Saka", "MID", 1, 9.5),
    (9, "Palmer", "MID", 4, 9.5),
    (10, "Mbeumo", "MID", 7, 7.5),
    (11, "Semenyo", "MID", 8, 6.5),
    (12, "Iwobi", "MID", 5, 5.0),
    (13, "Haaland", "FWD", 9, 14.0),
    (14, "Watkins", "FWD", 10, 8.5),
    (15, "Strand Larsen", "FWD", 11, 5.5),
    (16, "Flekken", "GKP", 7, 4.5),
    (18, "Munoz", "DEF", 6, 5.0),
    (20, "Cunha", "FWD", 11, 6.5),
    (21, "Areola", "GKP", 13, 4.5),
    (22, "Aina", "DEF", 12, 4.5),
    (23, "Eze", "MID", 6, 7.0),
    (24, "Joao Pedro", "FWD", 2, 6.0),
    (25, "Wirtz", "MID", 3, 8.0),
]


def _short(team_id: int) -> tuple[str, str]:
    team = next(t for t in TEAMS if t.id == team_id)
    return team.name, team.short_name


def make_player(
    pid: int,
    name: str,
    position: str,
    team_id: int,
    price: float,
    **kwargs,
) -> Player:
    team, short = _short(team_id)
    return Player(
        id=pid,
        name=name,
        team=team,
        team_id=team_id,
        team_short=short,
        position=position,
        price=price,
        form=kwargs.get("form", 5.0),
        status=kwargs.get("status", "a"),
        chance_of_playing_next_round=kwargs.get("chance_of_playing_next_round", 100),
        selected_by_percent=kwargs.get("selected_by_percent", 10.0),
        ep_next=kwargs.get("ep_next", 5.0),
        news=kwargs.get("news", ""),
    )


POOL = [make_player(*spec) for spec in _SPECS]
POOL_BY_ID = {p.id: p for p in POOL}
LEGAL_SQUAD = list(range(1, 16))
LEGAL_XI = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
GW1 = Event(id=1, name="Gameweek 1", is_next=True, deadline_time="2026-08-15T17:30:00Z")
