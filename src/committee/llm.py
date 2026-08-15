import os

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LlmError(Exception):
    pass


class LlmClient:
    def __init__(self, api_key: str | None = None, timeout: float = 120.0):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.timeout = timeout

    def complete(self, model: str, system: str, user: str) -> str:
        if not self.api_key:
            raise LlmError("OPENROUTER_API_KEY is not set")
        response = httpx.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
