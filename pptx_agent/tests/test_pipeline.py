import tempfile
import unittest
import zipfile
from pathlib import Path

from pptx_agent.config import Settings
from pptx_agent.planner import build_deck, deck_structure_text, extract_slide_count
from pptx_agent.pptx_writer import PptxWriter
from pptx_agent.research import Researcher


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


if __name__ == "__main__":
    unittest.main()
