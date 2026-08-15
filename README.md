# fpl-committee

[![CI](https://github.com/Mamoro98/fpl-committee/actions/workflows/ci.yml/badge.svg)](https://github.com/Mamoro98/fpl-committee/actions/workflows/ci.yml)

Three LLM agents (Scout, Risk, Hawk) debate my Fantasy Premier League move each gameweek. Each gives its own recommendation. I pick one. The picked agent earns reputation from my pick plus the real points the pick scores. Reputation is an EWMA (alpha 0.15, prior 17), so recent form matters and old luck fades.

## Weekly loop

```
committee memo --gw 3     # agents debate (2 rounds), memo lands in memos/gw3.md
committee pick scout --gw 3
committee settle --gw 3   # after the gameweek: real points -> reward -> scoreboard
```

Reward for the picked agent: `10 + transfer_in points + captain points`.

## Setup

```
pip install -e ".[dev]"
$env:OPENROUTER_API_KEY = "sk-or-..."
```

Models per agent are set in `src/committee/agents.py` (`DEFAULT_MODELS`), one OpenRouter id each. Different model families argue better.

## Development

```
pytest -v        # all tests offline, LLM + FPL API mocked
ruff check .
```

Built as a learning project for software engineering practice (TDD, branch + PR discipline, CI). Design decisions and build plan live in my notes.

## Docker

```
docker build -t fpl-committee .
docker run -e OPENROUTER_API_KEY fpl-committee memo --gw 3
```
