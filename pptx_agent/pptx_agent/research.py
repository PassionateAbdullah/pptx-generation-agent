from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any, Iterator

from .config import Settings
from .events import PHASE_RESEARCH, favicon_url, make_event, trust_tier


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    query: str = ""
    excerpt: str = ""
    engine: str = ""
    source_id: str = ""
    engines: list[str] | None = None
    queries: list[str] | None = None
    trust: str = ""

    def as_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {"title": self.title, "url": self.url, "snippet": self.snippet}
        if self.query:
            item["query"] = self.query
        if self.excerpt:
            item["excerpt"] = self.excerpt
        if self.engine:
            item["engine"] = self.engine
        if self.source_id:
            item["source_id"] = self.source_id
        if self.engines:
            item["engines"] = list(self.engines)
        if self.queries:
            item["queries"] = list(self.queries)
        if self.trust:
            item["trust"] = self.trust
        return item


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


class Researcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_search_meta: dict[str, Any] = {}

    def run(self, prompt: str, topic: str) -> dict[str, Any]:
        result: dict[str, Any] | None = None
        logs: list[str] = []
        for event in self.iter_run(prompt, topic):
            etype = event.get("type")
            if etype == "log":
                logs.append(event.get("text", ""))
            elif etype == "phase_end" and event.get("id") == PHASE_RESEARCH:
                result = event.get("result")
        if result is None:
            result = {
                "queries": [],
                "sources": [],
                "insights": [],
                "provider": "none",
            }
        result["logs"] = logs
        return result

    def iter_run(self, prompt: str, topic: str) -> Iterator[dict[str, Any]]:
        queries = self._queries(prompt, topic)[: self.settings.max_search_queries]
        provider = self._resolve_provider()

        yield make_event("phase_start", id=PHASE_RESEARCH, label="Research")
        yield make_event("provider", phase=PHASE_RESEARCH, provider=provider)
        yield make_event("log", phase=PHASE_RESEARCH, text="Research mode started.")
        yield make_event("log", phase=PHASE_RESEARCH, text="Building search queries from the user prompt.")
        yield make_event("queries", phase=PHASE_RESEARCH, items=list(queries))

        results: list[SearchResult] = []
        if provider == "none":
            yield make_event("log", phase=PHASE_RESEARCH, text="Live search disabled by SEARCH_PROVIDER=none.")
        else:
            yield make_event("log", phase=PHASE_RESEARCH, text=f"Search provider selected: {provider}.")
            if provider == "searxng" and self.settings.search_depth == "deep":
                yield make_event(
                    "log",
                    phase=PHASE_RESEARCH,
                    text=(
                        f"Deep SearXNG research enabled: {len(queries)} query angle(s), "
                        f"up to {self.settings.max_results_per_query} result(s) per query."
                    ),
                )
            for index, query in enumerate(queries, start=1):
                yield make_event(
                    "query",
                    phase=PHASE_RESEARCH,
                    query=query,
                    index=index,
                    total=len(queries),
                )
                yield make_event("log", phase=PHASE_RESEARCH, text=f"Searching: {query}")
                self._last_search_meta = {}
                try:
                    found = self._search(provider, query)
                except Exception as exc:  # noqa: BLE001
                    yield make_event(
                        "log",
                        phase=PHASE_RESEARCH,
                        text=f"Search failed for '{query}': {exc}",
                    )
                    continue
                kept = found[: self.settings.max_results_per_query]
                for result in kept:
                    result.query = query
                    yield make_event(
                        "result",
                        phase=PHASE_RESEARCH,
                        query=query,
                        title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                        engine=result.engine,
                        favicon=favicon_url(result.url),
                    )
                results.extend(kept)
                if self._last_search_meta:
                    yield make_event(
                        "search_summary",
                        phase=PHASE_RESEARCH,
                        query=query,
                        engines=self._last_search_meta.get("engines", {}),
                        unresponsive=self._last_search_meta.get("unresponsive", []),
                        base_url=self._last_search_meta.get("base_url", ""),
                    )
                yield make_event(
                    "log",
                    phase=PHASE_RESEARCH,
                    text=f"Found {len(found)} result(s), kept {len(kept)}.",
                )

        deduped = self._dedupe(results)[: self.settings.max_search_results]
        if not deduped:
            yield make_event(
                "log",
                phase=PHASE_RESEARCH,
                text="No live results available. Using local research fallback.",
            )
            deduped = self._fallback_sources(topic)
        elif self.settings.search_depth == "deep":
            enriched_count = self._enrich_sources(deduped)
            if enriched_count:
                yield make_event(
                    "log",
                    phase=PHASE_RESEARCH,
                    text=f"Fetched source text excerpts for {enriched_count} top source(s).",
                )

        for index, item in enumerate(deduped, start=1):
            item.source_id = f"S{index}"
            item.trust = trust_tier(item.url)
            if item.excerpt:
                yield make_event(
                    "source_excerpt",
                    phase=PHASE_RESEARCH,
                    source_id=item.source_id,
                    url=item.url,
                    excerpt=item.excerpt,
                )

        insights = self._insights(topic, deduped)
        yield make_event("insights", phase=PHASE_RESEARCH, items=list(insights))
        sources_dicts = [item.as_dict() for item in deduped]
        yield make_event("sources", phase=PHASE_RESEARCH, items=sources_dicts)
        yield make_event(
            "log",
            phase=PHASE_RESEARCH,
            text=f"Research complete: {len(deduped)} source item(s), {len(insights)} synthesized insight(s).",
        )
        result_payload = {
            "queries": list(queries),
            "sources": sources_dicts,
            "insights": list(insights),
            "provider": provider,
        }
        yield make_event("phase_end", id=PHASE_RESEARCH, result=result_payload)

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
        topic_query = topic.strip() or cleaned
        candidates = [
            cleaned,
            f"{topic_query} overview current situation",
            f"{topic_query} statistics report 2024 2025",
            f"{topic_query} key problems challenges gaps",
            f"{topic_query} policy regulation financing government",
            f"{topic_query} market size growth private sector",
            f"{topic_query} competitive landscape startups providers",
            f"{topic_query} investor pitch deck opportunity",
        ]
        deduped: list[str] = []
        seen: set[str] = set()
        for query in candidates:
            query = query.strip()
            key = query.lower()
            if query and key not in seen:
                seen.add(key)
                deduped.append(query)
        return deduped

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
        page_count = 2 if self.settings.search_depth == "deep" else 1
        for base_url in self._searxng_base_urls():
            if base_url.endswith("/search"):
                search_url = base_url
            else:
                search_url = f"{base_url}/search"
            collected: list[SearchResult] = []
            engines_seen: dict[str, int] = {}
            unresponsive: list[list[str]] = []
            for page in range(1, page_count + 1):
                url = search_url + "?" + urllib.parse.urlencode(
                    {
                        "q": query,
                        "format": "json",
                        "language": "en",
                        "safesearch": "0",
                        "categories": "general,news,science",
                        "pageno": page,
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
                    errors.append(f"{base_url} page {page}: {exc}")
                    break
                for item in data.get("results", []):
                    if not item.get("url"):
                        continue
                    engine = str(item.get("engine") or "")
                    if engine:
                        engines_seen[engine] = engines_seen.get(engine, 0) + 1
                    collected.append(
                        SearchResult(
                            title=item.get("title", "Untitled"),
                            url=item.get("url", ""),
                            snippet=item.get("content") or item.get("snippet", ""),
                            engine=engine,
                        )
                    )
                for entry in data.get("unresponsive_engines", []) or []:
                    unresponsive.append(list(entry) if isinstance(entry, (list, tuple)) else [str(entry)])
            if collected:
                self._last_search_meta = {
                    "engines": engines_seen,
                    "unresponsive": unresponsive,
                    "base_url": base_url,
                }
                return self._dedupe(collected)
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
        seen: dict[str, SearchResult] = {}
        order: list[str] = []
        for result in results:
            key = result.url.lower().rstrip("/")
            if not key:
                continue
            if key in seen:
                existing = seen[key]
                if result.engine and result.engine not in (existing.engines or []):
                    existing.engines = (existing.engines or [existing.engine]) + [result.engine]
                if result.query and result.query not in (existing.queries or []):
                    existing.queries = (existing.queries or [existing.query]) + [result.query]
                if not existing.excerpt and result.excerpt:
                    existing.excerpt = result.excerpt
                continue
            if result.engine and not result.engines:
                result.engines = [result.engine]
            if result.query and not result.queries:
                result.queries = [result.query]
            seen[key] = result
            order.append(key)
        return [seen[k] for k in order]

    def _fallback_sources(self, topic: str) -> list[SearchResult]:
        return [
            SearchResult(
                title=f"{topic.title()} research plan",
                url="local://research-plan",
                snippet="A useful deck should explain the current landscape, main stakeholder problems, market or policy context, proposed opportunity, risks, and next steps.",
            ),
            SearchResult(
                title=f"{topic.title()} evidence checklist",
                url="local://evidence-checklist",
                snippet="The strongest slides use current statistics, named stakeholders, operating constraints, and concrete examples instead of generic claims.",
            ),
            SearchResult(
                title=f"{topic.title()} pitch narrative",
                url="local://pitch-narrative",
                snippet="A pitch narrative should connect problem urgency, differentiated response, implementation path, business model, measurable impact, and the ask.",
            ),
        ]

    def _insights(self, topic: str, sources: list[SearchResult]) -> list[str]:
        insights = [f"Keep the deck anchored on {topic}, not a generic startup template."]
        source_text = " ".join(
            f"{item.title}. {item.snippet} {item.excerpt}" for item in sources
        )
        lowered = source_text.lower()

        if any(term in lowered for term in ["primary", "secondary", "tertiary", "community clinic"]):
            insights.append(
                "Map the system structure clearly, including primary, secondary, tertiary, and community-level delivery where relevant."
            )
        if any(term in lowered for term in ["challenge", "gap", "shortage", "access", "quality"]):
            insights.append(
                "Separate the core problems from symptoms: access, quality, affordability, workforce, infrastructure, and trust should not be merged into one claim."
            )
        if any(term in lowered for term in ["market", "growth", "private", "investment", "startup"]):
            insights.append(
                "For investor slides, connect public need to a credible private-sector or partnership opportunity instead of only describing the sector."
            )
        if any(term in lowered for term in ["government", "policy", "regulation", "financing", "budget"]):
            insights.append(
                "Include policy, regulation, and financing constraints because they affect adoption speed and buyer decisions."
            )

        for source in sources:
            sentence = self._first_sentence(source.excerpt or source.snippet)
            if not sentence:
                continue
            insight = f"{source.title}: {sentence}"
            if insight not in insights:
                insights.append(insight)
            if len(insights) >= 8:
                break

        return insights[:8]

    def _enrich_sources(self, sources: list[SearchResult]) -> int:
        enriched = 0
        for source in sources[:6]:
            excerpt = self._fetch_source_excerpt(source.url)
            if excerpt:
                source.excerpt = excerpt
                enriched += 1
        return enriched

    def _fetch_source_excerpt(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return ""
        lower_url = url.lower().split("?", 1)[0]
        if lower_url.endswith((".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx", ".zip")):
            return ""
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "ManusPptxAgent/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return ""
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read(self.settings.max_source_chars * 8)
        except Exception:
            return ""

        text = raw.decode(charset, errors="replace")
        if "text/html" in content_type:
            parser = _HTMLTextExtractor()
            parser.feed(text)
            text = parser.text()
        return self._clean_text(text)[: self.settings.max_source_chars].strip()

    def _first_sentence(self, text: str) -> str:
        cleaned = self._clean_text(text)
        cleaned = re.sub(r"\bMissing:.*$", "", cleaned).strip()
        if not cleaned:
            return ""
        sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
        return sentence[:260].rstrip(" ,;:-")

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", unescape(text)).strip()
