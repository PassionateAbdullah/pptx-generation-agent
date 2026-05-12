from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Settings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class Researcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, prompt: str, topic: str) -> dict[str, Any]:
        queries = self._queries(prompt, topic)
        logs = [
            "Research mode started.",
            "Building search queries from the user prompt.",
        ]
        results: list[SearchResult] = []

        provider = self._resolve_provider()
        if provider == "none":
            logs.append("Live search disabled by SEARCH_PROVIDER=none.")
        else:
            logs.append(f"Search provider selected: {provider}.")
            for query in queries:
                logs.append(f"Searching: {query}")
                try:
                    results.extend(self._search(provider, query))
                except Exception as exc:  # noqa: BLE001
                    logs.append(f"Search failed for '{query}': {exc}")
                if len(results) >= self.settings.max_search_results:
                    break

        deduped = self._dedupe(results)[: self.settings.max_search_results]
        if not deduped:
            logs.append("No live results available. Using local research fallback.")
            deduped = self._fallback_sources(topic)

        insights = self._insights(topic, deduped)
        logs.append(
            f"Research complete: {len(deduped)} source item(s), {len(insights)} synthesized insight(s)."
        )
        return {
            "queries": queries,
            "sources": [item.as_dict() for item in deduped],
            "insights": insights,
            "logs": logs,
            "provider": provider,
        }

    def _resolve_provider(self) -> str:
        provider = self.settings.search_provider
        if provider in {"searx", "searxng", "local-searxng"}:
            return "searxng"
        if provider != "auto":
            return provider
        if self.settings.searxng_url:
            return "searxng"
        if self.settings.brave_search_api_key:
            return "brave"
        if self.settings.serper_api_key:
            return "serper"
        if self.settings.tavily_api_key:
            return "tavily"
        return "duckduckgo"

    def _queries(self, prompt: str, topic: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", prompt).strip()
        return [
            f"{topic} pitch deck structure investor slides",
            f"{topic} market size growth statistics enterprise adoption",
            f"{topic} competitive landscape business model traction metrics",
            cleaned,
        ]

    def _search(self, provider: str, query: str) -> list[SearchResult]:
        if provider == "searxng":
            return self._search_searxng(query)
        if provider == "brave":
            return self._search_brave(query)
        if provider == "serper":
            return self._search_serper(query)
        if provider == "tavily":
            return self._search_tavily(query)
        if provider == "duckduckgo":
            return self._search_duckduckgo(query)
        return []

    def _search_searxng(self, query: str) -> list[SearchResult]:
        errors: list[str] = []
        for base_url in self._searxng_base_urls():
            if base_url.endswith("/search"):
                search_url = base_url
            else:
                search_url = f"{base_url}/search"
            url = search_url + "?" + urllib.parse.urlencode(
                {
                    "q": query,
                    "format": "json",
                    "language": "en",
                    "safesearch": "0",
                    "categories": "general",
                }
            )
            try:
                data = self._request_json(
                    urllib.request.Request(
                        url,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": "ManusPptxAgent/0.1",
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{base_url}: {exc}")
                continue
            return [
                SearchResult(
                    title=item.get("title", "Untitled"),
                    url=item.get("url", ""),
                    snippet=item.get("content") or item.get("snippet", ""),
                )
                for item in data.get("results", [])
                if item.get("url")
            ]
        raise RuntimeError("; ".join(errors) or "No SearXNG URL configured.")

    def _searxng_base_urls(self) -> list[str]:
        raw_value = self.settings.searxng_url or "http://127.0.0.1:8888,http://127.0.0.1:8080"
        return [
            item.strip().rstrip("/")
            for item in raw_value.split(",")
            if item.strip()
        ]

    def _search_brave(self, query: str) -> list[SearchResult]:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": self.settings.max_search_results}
        )
        data = self._request_json(
            urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.settings.brave_search_api_key,
                },
            )
        )
        items = data.get("web", {}).get("results", [])
        return [
            SearchResult(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            )
            for item in items
            if item.get("url")
        ]

    def _search_serper(self, query: str) -> list[SearchResult]:
        body = json.dumps({"q": query, "num": self.settings.max_search_results}).encode("utf-8")
        data = self._request_json(
            urllib.request.Request(
                "https://google.serper.dev/search",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-API-KEY": self.settings.serper_api_key,
                },
            )
        )
        items = data.get("organic", [])
        return [
            SearchResult(
                title=item.get("title", "Untitled"),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
            for item in items
            if item.get("link")
        ]

    def _search_tavily(self, query: str) -> list[SearchResult]:
        body = json.dumps(
            {
                "api_key": self.settings.tavily_api_key,
                "query": query,
                "max_results": self.settings.max_search_results,
                "search_depth": "advanced",
            }
        ).encode("utf-8")
        data = self._request_json(
            urllib.request.Request(
                "https://api.tavily.com/search",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
        )
        return [
            SearchResult(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in data.get("results", [])
            if item.get("url")
        ]

    def _search_duckduckgo(self, query: str) -> list[SearchResult]:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        )
        data = self._request_json(urllib.request.Request(url, headers={"Accept": "application/json"}))
        results: list[SearchResult] = []
        abstract_url = data.get("AbstractURL")
        if abstract_url:
            results.append(
                SearchResult(
                    title=data.get("Heading") or query,
                    url=abstract_url,
                    snippet=data.get("AbstractText", ""),
                )
            )
        for topic in data.get("RelatedTopics", []):
            if "Topics" in topic:
                nested = topic.get("Topics", [])
            else:
                nested = [topic]
            for item in nested:
                url_value = item.get("FirstURL", "")
                text = item.get("Text", "")
                if url_value and text:
                    results.append(SearchResult(title=text.split(" - ")[0], url=url_value, snippet=text))
                if len(results) >= self.settings.max_search_results:
                    return results
        return results

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc

    def _dedupe(self, results: list[SearchResult]) -> list[SearchResult]:
        seen: set[str] = set()
        deduped: list[SearchResult] = []
        for result in results:
            key = result.url.lower().rstrip("/")
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return deduped

    def _fallback_sources(self, topic: str) -> list[SearchResult]:
        return [
            SearchResult(
                title=f"{topic.title()} investor deck pattern",
                url="local://pitch-deck-pattern",
                snippet="Strong pitch decks usually move from problem to solution, product proof, market, business model, traction, team, and ask.",
            ),
            SearchResult(
                title=f"{topic.title()} enterprise AI buying criteria",
                url="local://enterprise-ai-buying-criteria",
                snippet="Enterprise AI buyers evaluate data security, workflow integration, accuracy, latency, governance, total cost, and change management.",
            ),
            SearchResult(
                title=f"{topic.title()} go-to-market assumptions",
                url="local://gtm-assumptions",
                snippet="AI platform GTM narratives should tie a narrow beachhead use case to expansion across departments, usage growth, and defensible data loops.",
            ),
        ]

    def _insights(self, topic: str, sources: list[SearchResult]) -> list[str]:
        base = [
            f"Frame {topic} as a business outcome platform first, not a model demo.",
            "Investor decks need a crisp problem, differentiated product proof, market scope, traction, team credibility, and a specific ask.",
            "Enterprise AI claims are stronger when tied to measurable accuracy, latency, security, deployment, and cost improvements.",
            "A 15-slide deck can support richer product, architecture, GTM, and financial slides without overloading each page.",
        ]
        snippets = " ".join(item.snippet for item in sources).lower()
        if "security" in snippets or "privacy" in snippets:
            base.append("Security and data governance deserve their own proof point because they are common enterprise blockers.")
        if "market" in snippets or "growth" in snippets:
            base.append("Market slides should separate TAM, SAM, and an initial beachhead instead of quoting one large number.")
        return base[:6]
