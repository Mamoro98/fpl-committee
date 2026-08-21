import os
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_MODELS: tuple[tuple[str, str], ...] = (
    ("deepseek", "deepseek/deepseek-v4-flash"),
    ("qwen", "qwen/qwen3-235b-a22b-2507"),
    ("glm", "z-ai/glm-4.5-air"),
    ("minimax", "minimax/minimax-m2.7"),
    ("gemini", "google/gemini-3.7-flash"),
)


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _parse_models(raw: str | None) -> list[tuple[str, str]]:
    if not raw or not raw.strip():
        return [tuple(item) for item in DEFAULT_MODELS]
    models: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for item in raw.split(","):
        slug = item.strip()
        if not slug:
            continue
        name = slug.rsplit("/", 1)[-1]
        base = name
        suffix = 2
        while name in seen_names:
            name = f"{base}-{suffix}"
            suffix += 1
        seen_names.add(name)
        models.append((name, slug))
    return models or [tuple(item) for item in DEFAULT_MODELS]


class Settings(BaseModel):
    api_key: str
    models: list[tuple[str, str]] = Field(default_factory=lambda: [tuple(item) for item in DEFAULT_MODELS])
    max_tokens: int = 2000

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        max_tokens = os.environ.get("FPL_COMMITTEE_MAX_TOKENS")
        return cls(
            api_key=key,
            models=_parse_models(os.environ.get("FPL_COMMITTEE_MODELS")),
            max_tokens=int(max_tokens) if max_tokens else cls.model_fields["max_tokens"].default,
        )

    def members(self) -> list[tuple[str, str]]:
        return list(self.models)
