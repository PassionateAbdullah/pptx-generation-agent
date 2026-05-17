import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from pptx_agent.config import Settings
from pptx_agent.planner import build_deck, deck_structure_text, extract_slide_count, slide_content_markdown
from pptx_agent.pptx_writer import PptxWriter
from pptx_agent.research import Researcher, SearchResult


class PipelineTest(unittest.TestCase):
    def settings(self, root: Path) -> Settings:
        return Settings(
            root=root,
            host="127.0.0.1",
            port=8787,
            output_dir=root / "output",
            llm_api_key="",
            llm_base_url="",
            llm_model="",
            search_provider="none",
            searxng_url="http://127.0.0.1:8080",
            brave_search_api_key="",
            serper_api_key="",
            tavily_api_key="",
            max_search_results=3,
        )

    def test_slide_count_extraction(self):
        self.assertEqual(extract_slide_count("Create a 15-slide pitch deck"), 15)

    def test_deck_and_pptx_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            prompt = "Create a 15-slide pitch deck for our AI platform."
            research = Researcher(settings).run(prompt, "AI platform")
            deck, logs = build_deck(prompt, 15, research, settings)
            self.assertEqual(deck["slide_count"], 15)
            self.assertEqual(len(deck["slides"]), 15)
            self.assertIn("Problem", deck_structure_text(deck))
            self.assertTrue(logs)

            pptx_path = root / "deck.pptx"
            PptxWriter().write(deck, pptx_path)
            self.assertTrue(pptx_path.exists())
            with zipfile.ZipFile(pptx_path) as zf:
                names = set(zf.namelist())
                self.assertIn("ppt/presentation.xml", names)
                self.assertIn("ppt/slides/slide15.xml", names)
                self.assertIn("[Content_Types].xml", names)

    def test_searxng_result_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            researcher = Researcher(settings)
            researcher._request_json = lambda request: {  # type: ignore[method-assign]
                "results": [
                    {
                        "title": "AI pitch deck structure",
                        "url": "https://example.com/deck",
                        "content": "Problem, solution, market, traction, team, and ask.",
                    }
                ]
            }
            results = researcher._search_searxng("AI pitch deck")
            self.assertEqual(results[0].title, "AI pitch deck structure")
            self.assertEqual(results[0].url, "https://example.com/deck")

    def test_deep_research_searches_multiple_query_angles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = replace(
                self.settings(root),
                search_provider="searxng",
                search_depth="deep",
                max_search_results=6,
                max_search_queries=3,
                max_results_per_query=2,
            )
            researcher = Researcher(settings)
            calls: list[str] = []

            def fake_search(provider: str, query: str) -> list[SearchResult]:
                calls.append(query)
                return [
                    SearchResult(
                        title=f"{query} result {index}",
                        url=f"https://example.com/{len(calls)}-{index}",
                        snippet=f"Evidence for {query} item {index}.",
                    )
                    for index in range(4)
                ]

            researcher._search = fake_search  # type: ignore[method-assign]
            researcher._enrich_sources = lambda sources: 0  # type: ignore[method-assign]

            result = researcher.run("Create a deck on healthcare in Bangladesh", "healthcare in Bangladesh")
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(result["sources"]), 6)
            self.assertIn("Deep SearXNG research enabled", "\n".join(result["logs"]))

    def test_fallback_deck_uses_research_topic_instead_of_ai_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = {
                "sources": [
                    {
                        "title": "Health system of Bangladesh",
                        "url": "https://example.com/health",
                        "snippet": "The health care system of Bangladesh has primary, secondary, and tertiary levels.",
                    }
                ],
                "insights": [
                    "Map the system structure clearly, including primary, secondary, tertiary, and community-level delivery where relevant."
                ],
            }

            deck, logs = build_deck(
                "Create a slide on healthcare system in Bangladesh",
                10,
                research,
                settings,
            )
            content = slide_content_markdown(deck)
            self.assertIn("Healthcare System In Bangladesh", deck["title"])
            self.assertIn("primary, secondary, tertiary", content)
            self.assertNotIn("Generic AI", content)
            self.assertTrue(logs)


if __name__ == "__main__":
    unittest.main()
