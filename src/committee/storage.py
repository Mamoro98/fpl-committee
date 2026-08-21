import json
import re
from pathlib import Path

from committee.schema import Memo, Recommendation

_UNSAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_name(model: str) -> str:
    return _UNSAFE.sub("-", model)


def save_memo(memos_dir: Path, memo: Memo) -> Path:
    folder = memos_dir / f"gw{memo.gameweek}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{memo.role}-{_safe_name(memo.model)}.json"
    path.write_text(memo.model_dump_json(indent=2), encoding="utf-8")
    return path


def append_ledger(ledger_path: Path, recommendation: Recommendation) -> None:
    records: list[dict] = []
    if ledger_path.exists():
        records = json.loads(ledger_path.read_text(encoding="utf-8"))
    records.append(
        {
            "gameweek": recommendation.gameweek,
            "mode": recommendation.mode,
            "squad_ids": recommendation.squad_ids,
            "xi": recommendation.xi,
            "captain": recommendation.captain,
            "vice_captain": recommendation.vice_captain,
            "formation": recommendation.formation,
            "budget_used": recommendation.budget_used,
            "bank": recommendation.bank,
            "transfers": [t.model_dump() for t in recommendation.transfers],
            "hits": recommendation.hits,
            "chip": recommendation.chip,
            "locked_ids": recommendation.locked_ids,
            "rationale": recommendation.rationale,
            "errors": recommendation.errors,
            "usage": recommendation.usage.model_dump(),
            "usage_by_call": [
                {
                    "model": m.model,
                    "model_id": m.model_id,
                    "role": m.role,
                    "error": m.error,
                    **m.usage.model_dump(),
                }
                for m in recommendation.memos
            ],
        }
    )
    ledger_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
