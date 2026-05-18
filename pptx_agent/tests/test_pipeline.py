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

    # ----- Phase 9: image embed + search -----

    def test_image_resolve_local_only_inside_job(self):
        from pptx_agent.images import resolve_local_image
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "job123"
            (job_dir / "media").mkdir(parents=True)
            f = job_dir / "media" / "abc.png"
            f.write_bytes(b"\x89PNG\r\n")
            self.assertEqual(resolve_local_image(job_dir, "/api/jobs/job123/media/abc.png"), f.resolve())
            self.assertIsNone(resolve_local_image(job_dir, "/api/jobs/other/media/abc.png"))
            self.assertIsNone(resolve_local_image(job_dir, "https://example.com/img.png"))
            self.assertIsNone(resolve_local_image(job_dir, "/api/jobs/job123/media/../../etc/passwd"))

    def test_pptx_embeds_image_block_with_local_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            prompt = "Create a 5-slide pitch deck for our platform."
            research = Researcher(settings).run(prompt, "platform")
            deck, _ = build_deck(prompt, 5, research, settings)
            job_dir = root / "job_smoke"
            (job_dir / "media").mkdir(parents=True)
            png = job_dir / "media" / "test.png"
            png.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
                b"\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            deck["slides"][1]["blocks"] = [
                {"id": "s2-b1-heading", "type": "heading", "props": {"text": "Image Slide", "level": 1}},
                {"id": "s2-b2-image", "type": "image", "props": {
                    "src": "/api/jobs/job_smoke/media/test.png",
                    "alt": "test image",
                    "caption": "field photo",
                    "fit": "cover",
                }},
            ]
            pptx_path = root / "deck.pptx"
            writer = PptxWriter()
            writer.set_job_dir(job_dir)
            writer.write(deck, pptx_path)
            with zipfile.ZipFile(pptx_path) as zf:
                names = set(zf.namelist())
                self.assertIn("ppt/media/test.png", names)
                slide_xml = zf.read("ppt/slides/slide2.xml").decode()
                self.assertIn("<p:pic>", slide_xml)
                rels = zf.read("ppt/slides/_rels/slide2.xml.rels").decode()
                self.assertIn("../media/test.png", rels)
                ct = zf.read("[Content_Types].xml").decode()
                self.assertIn('Extension="png"', ct)

    def test_pptx_image_block_external_url_falls_back_to_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            deck, _ = build_deck("Deck", 5, Researcher(settings).run("Deck", "x"), settings)
            deck["slides"][0]["blocks"] = [
                {"id": "s1-b1-image", "type": "image", "props": {"src": "https://example.com/x.png", "alt": "alt"}}
            ]
            pptx_path = root / "deck.pptx"
            PptxWriter().write(deck, pptx_path)
            with zipfile.ZipFile(pptx_path) as zf:
                slide1 = zf.read("ppt/slides/slide1.xml").decode()
                self.assertNotIn("<p:pic>", slide1)
                self.assertIn("[image:", slide1)

    # ----- Phase 8: dynamic block composition + auto charts -----

    def test_extract_numeric_series_picks_year_pairs(self):
        from pptx_agent.dynamic_blocks import extract_numeric_series
        pairs = extract_numeric_series([
            "Healthcare 2020: 4.2% of GDP. 2021: 5.1% of GDP. 2022: 6.4% of GDP.",
        ])
        labels = [p[0] for p in pairs]
        values = [p[1] for p in pairs]
        self.assertIn("2020", labels)
        self.assertIn("2021", labels)
        self.assertIn("2022", labels)
        self.assertIn(4.2, values)
        self.assertIn(5.1, values)
        self.assertIn(6.4, values)

    def test_chart_block_from_research_returns_none_when_no_numbers(self):
        from pptx_agent.dynamic_blocks import chart_block_from_research
        block = chart_block_from_research(2, {"insights": ["No numbers here at all."], "sources": []})
        self.assertIsNone(block)

    def test_compose_slide_blocks_varies_by_layout(self):
        from pptx_agent.dynamic_blocks import compose_slide_blocks
        research = {"sources": [], "insights": []}
        s_cover = {"number": 1, "layout": "cover", "title": "Hero", "subtitle": "sub", "eyebrow": "deck", "bullets": ["a"], "metrics": [{"label": "L", "value": "1"}]}
        s_problem = {"number": 2, "layout": "problem", "title": "Pain", "subtitle": "sub", "eyebrow": "Problem", "bullets": ["x", "y", "z"], "metrics": []}
        s_market = {"number": 3, "layout": "market", "title": "Market", "subtitle": "sub", "eyebrow": "Market", "bullets": ["a"], "metrics": []}
        blocks_cover = compose_slide_blocks(s_cover, 0, 5, research, "demo")
        blocks_problem = compose_slide_blocks(s_problem, 1, 5, research, "demo")
        blocks_market = compose_slide_blocks(s_market, 2, 5, research, "demo")
        shape_cover = "-".join(b["type"] for b in blocks_cover)
        shape_problem = "-".join(b["type"] for b in blocks_problem)
        shape_market = "-".join(b["type"] for b in blocks_market)
        self.assertNotEqual(shape_cover, shape_problem)
        self.assertNotEqual(shape_problem, shape_market)
        self.assertGreaterEqual(len(blocks_cover), 3)

    def test_planner_emits_varied_block_shapes(self):
        from pptx_agent.dynamic_blocks import variety_score
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = Researcher(settings).run("Pitch deck on solar microgrids", "solar microgrids")
            deck, _ = build_deck("Pitch deck on solar microgrids", 10, research, settings, theme="midnight")
            score = variety_score([s.get("blocks") or [] for s in deck["slides"]])
            self.assertGreaterEqual(score, 0.4)

    def test_planner_emits_chart_block_when_research_has_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = {
                "sources": [{
                    "title": "Spend",
                    "url": "https://example.com/s",
                    "excerpt": "2020: 4.2% of GDP. 2021: 5.1% of GDP. 2022: 6.4% of GDP. 2023: 7.9% of GDP.",
                    "snippet": "rising spend",
                }],
                "insights": ["Spend rose from 4.2% in 2020 to 7.9% in 2023."],
                "queries": [],
            }
            deck, _ = build_deck("Healthcare deck", 8, research, settings, theme="slate")
            charts = [b for s in deck["slides"] for b in (s.get("blocks") or []) if b["type"] == "chart"]
            self.assertGreater(len(charts), 0)
            populated = [c for c in charts if c["props"]["series"] and c["props"]["series"][0]["values"]]
            self.assertGreater(len(populated), 0)

    # ----- Phase 8.5: claim miner, topic families, hedge filter, dynamic outline, slide.md -----

    def test_claim_miner_extracts_concrete_facts_with_source_id(self):
        from pptx_agent.claim_miner import mine_claims
        research = {
            "sources": [{
                "source_id": "S1",
                "excerpt": "Government health spending is 0.4% of GDP. Bangladesh has 5.2 doctors per 10,000 people. NGO clinics serve 15 million Bangladeshis annually.",
                "snippet": "70% of rural patients travel more than 5 km for basic care.",
            }],
            "insights": [],
        }
        claims = mine_claims(research)
        kinds = {c.kind for c in claims}
        self.assertIn("percent", kinds)
        self.assertIn("number", kinds)
        self.assertTrue(all(c.source_id == "S1" for c in claims))
        # Generic meta phrases dropped.
        self.assertFalse(any("use real data" in c.text.lower() for c in claims))

    def test_hedge_filter_drops_meta_sentences_and_asserts_voice(self):
        from pptx_agent.hedge_filter import scrub_bullets, scrub_paragraph, is_meta_bullet
        self.assertTrue(is_meta_bullet("Use real data when available."))
        self.assertTrue(is_meta_bullet("The deck should clearly explain the gap."))
        cleaned = scrub_bullets([
            "Use real data when available",
            "Revenue grew 47% in 2023",
            "Healthcare in Bangladesh may help underserved regions",
        ])
        self.assertEqual(len(cleaned), 2)
        self.assertTrue(any("47" in c for c in cleaned))
        self.assertFalse(any("may help" in c.lower() for c in cleaned))
        para = scrub_paragraph("This slide should explain the gap. Revenue grew 47% in 2023.")
        self.assertIn("47", para)
        self.assertNotIn("should explain", para.lower())

    def test_topic_family_detection_picks_pitch_for_investor_prompts(self):
        from pptx_agent.topic_families import detect_family
        self.assertEqual(detect_family("Create a pitch deck for our seed round").name, "pitch_deck")
        self.assertEqual(detect_family("Customer success story case study").name, "case_study")
        self.assertEqual(detect_family("Product overview for our new launch").name, "product_overview")
        self.assertEqual(detect_family("Market analysis on smartphone sector").name, "market_analysis")
        # Unknown prompt → research_briefing fallback
        self.assertEqual(detect_family("Tell me about something").name, "research_briefing")

    def test_dynamic_outline_uses_research_claims_in_slide_titles(self):
        from pptx_agent.dynamic_outline import build_outline
        research = {
            "sources": [{
                "source_id": "S1",
                "excerpt": "By 2028 the market reaches $15 billion. Annual growth: 8.5% CAGR. Workforce shortage of 250,000.",
                "snippet": "Government spending: 0.4% of GDP.",
            }],
            "insights": ["Healthcare in Bangladesh is fragmented across public, NGO, and private tiers."],
        }
        deck = build_outline(
            "Create a 10-slide investor pitch deck on healthcare in Bangladesh.",
            "healthcare in Bangladesh", 10, research,
        )
        self.assertEqual(deck["family"], "pitch_deck")
        # At least one slide title should carry a concrete claim from the research.
        title_blob = " ".join(s["title"] for s in deck["slides"]).lower()
        self.assertTrue(
            "$15 billion" in title_blob or "8.5%" in title_blob or "fragmented" in title_blob,
            f"No research-anchored title found in: {title_blob}",
        )
        # At least one slide should carry inline source citation in bullets.
        bullet_blob = " ".join(b for s in deck["slides"] for b in s["bullets"])
        self.assertIn("[S1]", bullet_blob)

    def test_dynamic_outline_research_briefing_vs_pitch_produce_different_structures(self):
        from pptx_agent.dynamic_outline import build_outline
        research = {"sources": [], "insights": [], "queries": []}
        deck_pitch = build_outline("Investor pitch deck on X", "X", 8, research)
        deck_brief = build_outline("Research briefing on X", "X", 8, research)
        layouts_pitch = [s["layout"] for s in deck_pitch["slides"]]
        layouts_brief = [s["layout"] for s in deck_brief["slides"]]
        self.assertNotEqual(layouts_pitch, layouts_brief)
        self.assertEqual(deck_pitch["family"], "pitch_deck")
        self.assertEqual(deck_brief["family"], "research_briefing")

    def test_slide_md_emitter_matches_manus_format(self):
        from pptx_agent.slide_md import emit_slide_md
        deck = {
            "title": "Healthcare in Bangladesh Pitch Deck",
            "subtitle": "Investor pitch on the healthcare market",
            "topic": "healthcare in Bangladesh",
            "family": "pitch_deck",
            "audience": "Investors",
            "slides": [
                {"number": 1, "layout": "cover", "eyebrow": "Cover",
                 "title": "Healthcare in Bangladesh", "subtitle": "", "bullets": [], "metrics": []},
                {"number": 2, "layout": "problem", "eyebrow": "Problem",
                 "title": "The 0.4% GDP problem",
                 "subtitle": "Government health spending undershoots demand",
                 "bullets": ["Government spending is 0.4% of GDP [S1]", "Out-of-pocket pays 67% [S1]"],
                 "metrics": [{"label": "GDP", "value": "0.4%"}], "citations": ["S1"]},
            ],
        }
        md = emit_slide_md(deck)
        self.assertIn("# Healthcare in Bangladesh Pitch Deck", md)
        self.assertIn("## Cover", md)
        self.assertIn("## Slide 2", md)
        self.assertIn("The 0.4% GDP problem", md)
        self.assertIn("- Government spending is 0.4% of GDP [S1]", md)
        self.assertIn("**0.4%** — GDP", md)
        self.assertIn("Sources: S1", md)

    def test_planner_writes_slide_md_artifact(self):
        from pptx_agent.pipeline import write_deck_artifacts
        from pptx_agent.planner import build_deck
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = Researcher(settings).run("Pitch on healthcare in Bangladesh", "healthcare in Bangladesh")
            deck, _ = build_deck("Pitch on healthcare in Bangladesh", 8, research, settings)
            job_dir = root / "job1"
            artifacts = write_deck_artifacts(deck, job_dir, research)
            self.assertTrue((job_dir / "slide.md").exists())
            md = (job_dir / "slide.md").read_text(encoding="utf-8")
            self.assertIn("##", md)
            self.assertIn("slide_md", artifacts)

    # ----- Phase 12: regenerate single slide -----

    def test_parse_directives_extracts_typed_intents(self):
        from pptx_agent.regen import parse_directives
        d = parse_directives("Shorten this and add a chart with more numbers, focus on traction")
        self.assertTrue(d.shorten)
        self.assertTrue(d.add_chart)
        self.assertTrue(d.more_numbers)
        self.assertIn("traction", d.use_keywords)
        d2 = parse_directives("Make it less corporate and refresh research")
        self.assertTrue(d2.less_corporate)
        self.assertTrue(d2.refresh_research)
        d3 = parse_directives("Make this slide about hospital staffing")
        self.assertEqual(d3.swap_topic, "hospital staffing")

    def test_regenerate_slide_swaps_content_with_directive(self):
        from pptx_agent.regen import regenerate_slide
        from pptx_agent.planner import build_deck
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            research = {
                "sources": [{
                    "source_id": "S1", "title": "BD Health",
                    "url": "https://e/x",
                    "excerpt": "Bangladesh has 5.2 doctors per 10,000. Telemedicine reached 12% in 2023. Market size $10 billion. Annual CAGR 8.5%.",
                    "snippet": "Workforce shortage of 250,000.",
                }],
                "insights": ["Healthcare in Bangladesh is fragmented across public and private."],
            }
            deck, _ = build_deck(
                "Create a pitch deck on healthcare in Bangladesh", 8, research, settings, theme="midnight",
            )
            before_slide_3 = dict(deck["slides"][2])
            new_slide = regenerate_slide(
                deck, slide_number=3,
                instruction="Add a chart and use more numbers",
                settings=settings,
                refresh_research=False,
            )
            self.assertEqual(new_slide["number"], 3)
            # Forced chart block present
            block_types = [b["type"] for b in new_slide["blocks"]]
            self.assertIn("chart", block_types)
            # Has regenerate metadata
            self.assertIn("regenerate_instruction", new_slide)
            self.assertEqual(new_slide["regenerate_instruction"], "Add a chart and use more numbers")

    def test_regenerate_slide_unknown_raises(self):
        from pptx_agent.regen import regenerate_slide
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            with self.assertRaises(KeyError):
                regenerate_slide({"slides": []}, 9, "shorter", settings)

    def test_image_broker_search_parses_searxng_payload(self):
        from unittest import mock
        from pptx_agent.images import ImageBroker
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            object.__setattr__(settings, "search_provider", "searxng")
            object.__setattr__(settings, "searxng_url", "http://example.invalid")
            broker = ImageBroker(settings)
            sample_payload = {
                "results": [
                    {
                        "title": "Solar panels",
                        "img_src": "https://example.com/img1.jpg",
                        "thumbnail_src": "https://example.com/thumb1.jpg",
                        "engine": "duckduckgo",
                        "img_width": 1200,
                        "img_height": 800,
                    },
                    {
                        "title": "Solar field",
                        "img_src": "https://example.com/img2.png",
                        "thumbnail_src": "",
                        "engine": "bing",
                    },
                ]
            }

            class FakeResp:
                def __init__(self, body): self._body = body
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self):
                    import json as _j
                    return _j.dumps(self._body).encode()

            with mock.patch("urllib.request.urlopen", return_value=FakeResp(sample_payload)):
                results = broker.search("solar panels", max_n=5)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].url, "https://example.com/img1.jpg")
            self.assertEqual(results[0].thumbnail_url, "https://example.com/thumb1.jpg")
            self.assertEqual(results[1].thumbnail_url, "https://example.com/img2.png")


if __name__ == "__main__":
    unittest.main()
