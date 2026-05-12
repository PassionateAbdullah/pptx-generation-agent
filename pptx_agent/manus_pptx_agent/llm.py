from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import Settings


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_api_key and self.settings.llm_model)

    def complete_json(self, system: str, user: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        base_url = self._chat_url(self.settings.llm_base_url)
        body = json.dumps(
            {
                "model": self.settings.llm_model,
                "temperature": 0.35,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

        content = data["choices"][0]["message"]["content"]
        return json.loads(content)

    def _chat_url(self, value: str) -> str:
        base = (value or "https://api.openai.com/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

