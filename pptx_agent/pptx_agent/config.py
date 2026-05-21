from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    root: Path
    host: str
    port: int
    output_dir: Path
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    search_provider: str
    searxng_url: str
    brave_search_api_key: str
    serper_api_key: str
    tavily_api_key: str
    max_search_results: int
    search_depth: str = "deep"
    max_search_queries: int = 7
    max_results_per_query: int = 4
    max_source_chars: int = 1400


def load_settings(root: Path) -> Settings:
    for key, value in _read_env_file(root / ".env").items():
        os.environ.setdefault(key, value)

    try:
        port = int(_env("PORT", "8787"))
    except ValueError:
        port = 8787

    try:
        max_search_results = max(1, min(30, int(_env("MAX_SEARCH_RESULTS", "18"))))
    except ValueError:
        max_search_results = 18
    try:
        max_search_queries = max(1, min(10, int(_env("MAX_SEARCH_QUERIES", "7"))))
    except ValueError:
        max_search_queries = 7
    try:
        max_results_per_query = max(1, min(10, int(_env("MAX_RESULTS_PER_QUERY", "4"))))
    except ValueError:
        max_results_per_query = 4
    try:
        # Ceiling matches pptx_agent.fetch._MAX_CHARS_CEILING so the new
        # fetch_url helper can pull a full article body when one is
        # available. Default 6000 is enough for most pages without blowing
        # the LLM context budget downstream.
        max_source_chars = max(300, min(10000, int(_env("MAX_SOURCE_CHARS", "6000"))))
    except ValueError:
        max_source_chars = 6000

    output_dir = root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    search_depth = (_env("SEARCH_DEPTH", "deep") or "deep").lower()
    if search_depth not in {"standard", "deep"}:
        search_depth = "deep"

    return Settings(
        root=root,
        host=_env("HOST", "127.0.0.1") or "127.0.0.1",
        port=port,
        output_dir=output_dir,
        llm_api_key=_env("LLM_API_KEY"),
        llm_base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_model=_env("LLM_MODEL"),
        search_provider=(_env("SEARCH_PROVIDER", "auto") or "auto").lower(),
        searxng_url=_env("SEARXNG_URL", "http://127.0.0.1:8888,http://127.0.0.1:8080"),
        brave_search_api_key=_env("BRAVE_SEARCH_API_KEY"),
        serper_api_key=_env("SERPER_API_KEY"),
        tavily_api_key=_env("TAVILY_API_KEY"),
        max_search_results=max_search_results,
        search_depth=search_depth,
        max_search_queries=max_search_queries,
        max_results_per_query=max_results_per_query,
        max_source_chars=max_source_chars,
    )
