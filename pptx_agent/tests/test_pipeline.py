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

    def test_extract_topic_strips_command_and_deck_nouns(self):
        from pptx_agent.planner import extract_topic
        self.assertEqual(
            extract_topic("Create a 10-slide pitch deck for our AI platform."),
            "AI platform",
        )
        self.assertEqual(
            extract_topic("Briefing on healthcare in Bangladesh"),
            "healthcare in Bangladesh",
        )
        self.assertEqual(
            extract_topic("Make a 12-slide investor deck about agentic AI reliability"),
            "agentic AI reliability",
        )
        self.assertEqual(
            extract_topic("Build a presentation on solar microgrids in Africa"),
            "solar microgrids in Africa",
        )

    def test_extract_topic_does_not_collapse_non_ai_prompts_to_ai_platform(self):
        from pptx_agent.planner import extract_topic
        # Old default of "AI platform" swallowed every prompt that mentioned AI
        # in passing — even when the real topic was healthcare/education.
        topic = extract_topic("Education and AI in classrooms")
        self.assertNotEqual(topic, "AI platform")
        self.assertIn("classrooms", topic.lower())
        self.assertIn("education", topic.lower())

    def test_deck_audit_flags_cover_with_citations(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "T",
            "research": {"sources": [{"source_id": "S1", "title": "A", "url": "u"}]},
            "slides": [{
                "number": 1, "layout": "cover", "citations": ["S1"],
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "y", "level": 1}},
                    {"type": "subheading", "props": {"text": "z"}},
                ],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertIn("cover-has-citations", codes)

    def test_deck_audit_flags_non_numeric_hero_stat(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "T",
            "research": {"sources": []},
            "slides": [{
                "number": 2, "layout": "metrics", "citations": [],
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "y", "level": 1}},
                    {"type": "hero_stat", "props": {
                        "value": "Convenience", "label": "user benefit", "source_id": ""}},
                ],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertIn("hero-stat-non-numeric", codes)

    def test_deck_audit_flags_chart_with_too_few_points(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "T",
            "research": {"sources": []},
            "slides": [{
                "number": 3, "layout": "market", "citations": [],
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "y", "level": 1}},
                    {"type": "chart", "props": {
                        "kind": "bar", "labels": ["2022", "2023"],
                        "series": [{"label": "x", "values": [1.0, 2.0]}]}},
                ],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertIn("chart-too-few-points", codes)

    def test_deck_audit_flags_unresolved_citation(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "T",
            "research": {"sources": [{"source_id": "S1", "title": "A", "url": "u"}]},
            "slides": [{
                "number": 4, "layout": "problem", "citations": ["S99"],
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "y", "level": 1}},
                    {"type": "callout", "props": {"tone": "warn", "text": "bad"}},
                ],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertIn("citation-unresolved", codes)

    def test_deck_audit_flags_missing_required_visual_for_market_layout(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "T",
            "research": {"sources": []},
            "slides": [{
                "number": 5, "layout": "market", "citations": [],
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "y", "level": 1}},
                    {"type": "paragraph", "props": {"text": "no visuals here"}},
                    {"type": "bullets", "props": {"items": ["a [S1]", "b [S1]"]}},
                ],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertIn("missing-required-visual", codes)

    def test_write_deck_artifacts_emits_audit_json_and_panel(self):
        from pptx_agent.pipeline import write_deck_artifacts
        from pptx_agent.planner import build_deck
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = Researcher(settings).run("briefing on solar", "solar")
            deck, _ = build_deck("briefing on solar", 5, research, settings)
            job_dir = root / "j-audit"
            artifacts = write_deck_artifacts(deck, job_dir, research)
            audit_path = job_dir / "audit.json"
            self.assertTrue(audit_path.exists())
            self.assertIn("audit", artifacts)
            self.assertIn("findings", artifacts["audit"])
            html = (job_dir / "slides.html").read_text(encoding="utf-8")
            # Audit panel renders inside slides.html when there are findings.
            if artifacts["audit"]["findings"]:
                self.assertIn("audit-panel", html)

    def test_deck_and_pptx_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            prompt = "Create a 15-slide pitch deck for our AI platform."
            research = Researcher(settings).run(prompt, "AI platform")
            deck, logs = build_deck(prompt, 15, research, settings)
            self.assertEqual(deck["slide_count"], 15)
            self.assertEqual(len(deck["slides"]), 15)
            # Without LLM the planner emits an honest scaffold — slides are
            # numbered placeholders that prompt the user to configure
            # LLM_API_KEY. Verify structure text mentions all 15 slides.
            structure = deck_structure_text(deck)
            self.assertIn("(15 Slides)", structure)
            self.assertIn("15.", structure)
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

    def test_scaffold_outline_yields_titles_when_llm_disabled(self):
        # New contract: without LLM, the planner emits an honest scaffold —
        # numbered slides with a "configure LLM_API_KEY" callout. No fake
        # bullets, no recipe-generated charts. Block variety lives in the
        # LLM-authored path; offline mode is intentionally minimal.
        from pptx_agent.slide_author import scaffold_outline, _scaffold_slide
        outline = scaffold_outline("Pitch deck on solar microgrids", "solar microgrids", 10)
        self.assertEqual(len(outline["slides"]), 10)
        self.assertEqual(outline["slides"][0]["role"], "cover")
        self.assertEqual(outline["slides"][-1]["role"], "closing")
        slide = _scaffold_slide(outline["slides"][2])
        block_types = [b["type"] for b in slide["blocks"]]
        self.assertEqual(block_types[0], "eyebrow")
        self.assertEqual(block_types[1], "heading")
        self.assertIn("callout", block_types)

    def test_planner_outline_pass_uses_deterministic_research_without_llm(self):
        from pptx_agent.planner import iter_build_deck
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(Path(tmp))
            research = {
                "queries": ["healthcare bangladesh trends"],
                "insights": [
                    "Healthcare in Bangladesh has a three-tier delivery model.",
                    "Workforce and access constraints remain severe in rural regions.",
                ],
                "sources": [
                    {
                        "source_id": "S1",
                        "title": "Health system of Bangladesh",
                        "url": "https://example.com/health",
                        "snippet": "Primary, secondary, and tertiary care layers.",
                    }
                ],
            }
            events = list(iter_build_deck("Solar microgrids deck", 6, research, settings))
            phase_ends = [e for e in events if e.get("type") == "phase_end" and e.get("id") == "content"]
            self.assertEqual(len(phase_ends), 1)
            deck = phase_ends[0]["result"]
            self.assertEqual(len(deck["slides"]), 6)
            block_types = [b.get("type") for s in deck["slides"] for b in (s.get("blocks") or [])]
            self.assertIn("bullets", block_types)
            self.assertTrue(any(t in {"highlight", "table", "diagram", "metric_row"} for t in block_types))
            text_blob = " ".join(str(s.get("title", "")) + " " + str(s.get("subtitle", "")) for s in deck["slides"])
            self.assertNotIn("LLM_API_KEY", text_blob)

    def test_table_block_extracts_entity_value_rows_from_research(self):
        from pptx_agent.dynamic_blocks import table_block_from_research
        research = {
            "insights": [],
            "sources": [{
                "source_id": "S1",
                "excerpt": "Market share: Public: 60%, NGO: 15%, Private: 25%. Other smaller players hold the rest.",
                "snippet": "",
            }],
        }
        block = table_block_from_research(5, research)
        self.assertIsNotNone(block)
        self.assertEqual(block["type"], "table")
        rows = block["props"]["rows"]
        entities = {r[0].lower() for r in rows}
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue({"public", "ngo", "private"}.issubset(entities))
        self.assertTrue(any("%" in r[1] for r in rows))

    def test_table_block_returns_none_without_entity_value_pattern(self):
        from pptx_agent.dynamic_blocks import table_block_from_research
        block = table_block_from_research(
            5,
            {"insights": ["No structured comparisons here."], "sources": []},
        )
        self.assertIsNone(block)

    def test_outline_emits_table_for_comparison_slide_when_research_supplies_one(self):
        from pptx_agent.dynamic_outline import build_outline
        research = {
            "sources": [{
                "source_id": "S1",
                "title": "Segments",
                "excerpt": "Market share: Public: 60%, NGO: 15%, Private: 25%. Competition vs incumbents differs.",
                "snippet": "Workforce: 250000.",
            }],
            "insights": [],
        }
        deck = build_outline(
            "Investor pitch deck on healthcare in Bangladesh", "healthcare in Bangladesh", 10, research,
        )
        types_per_slide = [[b.get("type") for b in s.get("blocks", [])] for s in deck["slides"]]
        flat = [t for slide in types_per_slide for t in slide]
        self.assertIn("table", flat)

    def test_slide_author_uses_assigned_sources_with_full_excerpts(self):
        from pptx_agent.slide_author import _pick_sources
        research = {
            "sources": [
                {"source_id": "S1", "title": "A", "url": "u1", "excerpt": "Big excerpt 1" * 50},
                {"source_id": "S2", "title": "B", "url": "u2", "excerpt": "Big excerpt 2" * 50},
                {"source_id": "S3", "title": "C", "url": "u3", "excerpt": "Big excerpt 3" * 50},
            ],
        }
        picked = _pick_sources(research, ["S2", "S3"])
        ids = [p["source_id"] for p in picked]
        self.assertEqual(ids, ["S2", "S3"])
        # Full excerpts (up to 2400 chars) survive the pick — slide author
        # needs the raw text to lift numbers and entities verbatim.
        self.assertGreater(len(picked[0]["excerpt"]), 200)

    def test_ground_blocks_drops_chart_with_invented_values(self):
        from pptx_agent.slide_author import _ground_blocks
        sources = [{"source_id": "S1", "excerpt": "Spend reached 4.2% in 2020 and 7.9% in 2023."}]
        good_chart = {
            "id": "s1-chart", "type": "chart",
            "props": {"kind": "line", "title": "Spend",
                      "labels": ["2020", "2023"],
                      "series": [{"label": "Spend", "values": [4.2, 7.9]}]},
        }
        bad_chart = {
            "id": "s2-chart", "type": "chart",
            "props": {"kind": "bar", "title": "Made up",
                      "labels": ["X", "Y", "Z"],
                      "series": [{"label": "Fake", "values": [11, 22, 33]}]},
        }
        out = _ground_blocks([good_chart, bad_chart], sources)
        types = [b["type"] for b in out]
        self.assertEqual(types, ["chart"])
        self.assertEqual(out[0]["id"], "s1-chart")

    def test_ground_blocks_drops_hero_stat_with_no_source_value(self):
        from pptx_agent.slide_author import _ground_blocks
        sources = [{"source_id": "S1", "excerpt": "Workforce gap is 250,000 nurses."}]
        good_hero = {"id": "h1", "type": "hero_stat",
                     "props": {"value": "250,000", "label": "Workforce gap", "source_id": "S1"}}
        bad_hero = {"id": "h2", "type": "hero_stat",
                    "props": {"value": "$15B", "label": "TAM", "source_id": "S1"}}
        out = _ground_blocks([good_hero, bad_hero], sources)
        self.assertEqual([b["id"] for b in out], ["h1"])

    def test_ground_blocks_filters_table_rows_lacking_excerpt_match(self):
        from pptx_agent.slide_author import _ground_blocks
        sources = [{"source_id": "S1",
                    "excerpt": "Public sector is 60%. NGO clinics serve 15%. Private is 25%."}]
        table = {"id": "t1", "type": "table",
                 "props": {"headers": ["Segment", "Share"],
                           "rows": [["Public", "60%"], ["NGO", "15%"],
                                    ["Private", "25%"], ["FakeCo", "99%"]]}}
        out = _ground_blocks([table], sources)
        self.assertEqual(len(out), 1)
        rows = out[0]["props"]["rows"]
        labels = {r[0] for r in rows}
        self.assertIn("Public", labels)
        self.assertNotIn("FakeCo", labels)

    def test_extract_signals_pulls_verbatim_claim_sentences(self):
        from pptx_agent.slide_author import _extract_signals
        sources = [{
            "source_id": "S1",
            "excerpt": "Government spending is 0.4% of GDP. Workforce gap reached 250,000.",
        }]
        signals = _extract_signals(sources)
        kinds = {s["kind"] for s in signals}
        self.assertTrue({"percent", "number"} & kinds)
        self.assertTrue(all(s["source_id"] == "S1" for s in signals))

    def test_slide_author_loads_prompt_templates_from_disk(self):
        from pptx_agent.prompts import load
        outline_prompt = load("outline")
        slide_prompt = load("slide")
        self.assertIn("publication-ready deck", outline_prompt)
        self.assertIn("focus_keywords", outline_prompt)
        # New grounded prompt: signals + validator + density rules.
        self.assertIn("signals", slide_prompt)
        self.assertIn("Grounding rules", slide_prompt)
        self.assertIn("layout-block contract", slide_prompt.lower())
        self.assertIn("Never invent numbers", slide_prompt)

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

    def test_pipeline_writes_per_slide_html_files(self):
        from pptx_agent.pipeline import write_deck_artifacts
        from pptx_agent.planner import build_deck
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = Researcher(settings).run("Deck on solar", "solar")
            deck, _ = build_deck("Deck on solar", 5, research, settings)
            job_dir = root / "job-html"
            write_deck_artifacts(deck, job_dir, research)
            for n in range(1, 6):
                p = job_dir / f"slide-{n:02d}.html"
                self.assertTrue(p.exists(), f"missing {p.name}")
                txt = p.read_text(encoding="utf-8")
                self.assertIn("<!doctype html>", txt)
                self.assertIn(f'data-slide="{n}"', txt)

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

    def test_pipeline_writes_layout_audit_artifacts(self):
        from pptx_agent.pipeline import write_deck_artifacts
        from pptx_agent.planner import build_deck
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = Researcher(settings).run("Pitch on healthcare in Bangladesh", "healthcare in Bangladesh")
            deck, _ = build_deck("Pitch on healthcare in Bangladesh", 8, research, settings)
            job_dir = root / "job-layout"
            artifacts = write_deck_artifacts(deck, job_dir, research)
            self.assertTrue((job_dir / "layout_report.md").exists())
            self.assertTrue((job_dir / "layout_report.json").exists())
            report = artifacts.get("layout_report", {})
            self.assertIn("summary", report)
            self.assertIn("status", report.get("summary", {}))

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

    # ----- Step 1: intake (source relevance + story validation + targeted queries) -----

    def test_intake_score_source_weights_high_trust(self):
        from pptx_agent.intake import score_source
        topic = "healthcare in Bangladesh"
        gov = {"title": "Healthcare in Bangladesh", "url": "https://www.mohfw.gov.bd/x",
               "snippet": "healthcare bangladesh", "excerpt": ""}
        blog = {"title": "Healthcare in Bangladesh", "url": "https://example.blog/post",
                "snippet": "healthcare bangladesh", "excerpt": ""}
        score_gov, trust_gov = score_source(gov, topic)
        score_blog, trust_blog = score_source(blog, topic)
        self.assertEqual(trust_gov, "gov")
        self.assertEqual(trust_blog, "blog")
        # Identical text content + different trust tier → gov outscores blog.
        self.assertGreater(score_gov, score_blog)
        self.assertGreater(score_gov / max(score_blog, 1e-6), 2.0)

    def test_intake_filter_sources_rejects_off_topic_low_trust(self):
        from pptx_agent.intake import filter_sources
        sources = [
            {"title": "Healthcare Bangladesh report", "url": "https://who.int/bd",
             "snippet": "healthcare bangladesh maternal", "excerpt": ""},
            {"title": "Crypto news today", "url": "https://example.blog/crypto",
             "snippet": "bitcoin price chart", "excerpt": ""},
        ]
        kept, rejected = filter_sources(sources, "healthcare in Bangladesh")
        kept_urls = {s["url"] for s in kept}
        self.assertIn("https://who.int/bd", kept_urls)
        self.assertNotIn("https://example.blog/crypto", kept_urls)
        self.assertEqual(len(rejected), 1)
        self.assertIn("low relevance", rejected[0]["reason"])

    def test_intake_validate_story_flags_missing_required_roles(self):
        from pptx_agent.intake import validate_story
        outline = {
            "family": "pitch_deck",
            "slides": [
                {"number": 1, "role": "cover", "layout": "cover"},
                {"number": 2, "role": "solution", "layout": "solution"},
                {"number": 3, "role": "closing", "layout": "closing"},
            ],
        }
        gaps = validate_story(outline, "pitch_deck")
        gap_roles = {g.role for g in gaps}
        # pitch_deck requires problem + market + traction + ask among others.
        self.assertIn("problem", gap_roles)
        self.assertIn("market", gap_roles)
        self.assertIn("ask", gap_roles)

    def test_intake_targeted_queries_fires_only_for_data_heavy_slides(self):
        from pptx_agent.intake import targeted_queries
        chart_slide = {"needs_chart": True, "focus_keywords": ["spend", "gdp"],
                       "title": "Health spend rose"}
        plain_slide = {"needs_chart": False, "needs_table": False,
                       "needs_hero_stat": False, "focus_keywords": ["overview"]}
        qs_chart = targeted_queries(chart_slide, "healthcare in Bangladesh")
        qs_plain = targeted_queries(plain_slide, "healthcare in Bangladesh")
        self.assertEqual(len(qs_plain), 0)
        self.assertGreaterEqual(len(qs_chart), 1)
        self.assertTrue(any("statistics" in q for q in qs_chart))

    # ----- Step 2: agent_loop -----

    def test_quality_score_weighs_severity(self):
        from pptx_agent.agent_loop import quality_score
        audit = {"findings": [
            {"slide": 1, "severity": "error", "code": "x", "message": "x"},
            {"slide": 1, "severity": "warn", "code": "y", "message": "y"},
            {"slide": 2, "severity": "info", "code": "z", "message": "z"},
        ]}
        visual = {2: [{"code": "v", "severity": "error", "message": "v"}]}
        out = quality_score(audit, visual)
        # 1× error(10) + 1× warn(2) + 1× info(0.5) + 1× error(10) = 22.5
        self.assertEqual(out["score"], 22.5)
        self.assertEqual(out["by_severity"]["error"], 2)
        # Slide 1: error+warn = 12; slide 2: info+error = 10.5
        self.assertEqual(out["by_slide"][1], 12.0)
        self.assertEqual(out["by_slide"][2], 10.5)

    def test_run_loop_does_not_call_llm_when_no_slide_level_errors(self):
        from pptx_agent.agent_loop import run_loop
        from unittest.mock import MagicMock
        # Minimal cover slide. Deck-level audit may emit one info finding
        # ("missing-closing") but no slide-level errors → loop has no slide
        # to repair, so the LLM must never be invoked.
        deck = {
            "title": "T", "theme": "betopia", "topic": "x",
            "slides": [{
                "number": 1, "id": "slide-1", "layout": "cover",
                "title": "T", "subtitle": "", "eyebrow": "",
                "citations": [], "bullets": [], "metrics": [],
                "blocks": [
                    {"id": "s1-b1-eyebrow", "type": "eyebrow", "props": {"text": "x"}},
                    {"id": "s1-b2-heading", "type": "heading",
                     "props": {"text": "T", "level": 1}},
                    {"id": "s1-b3-sub", "type": "subheading", "props": {"text": "x"}},
                    {"id": "s1-b4-metric", "type": "metric_row",
                     "props": {"metrics": [{"label": "L", "value": "10"}]}},
                ],
            }],
            "research": {"sources": []},
        }
        events = []
        llm = MagicMock(spec=["complete_json"])
        run_loop(deck, deck["research"], {}, llm, max_passes=2,
                 on_event=events.append)
        llm.complete_json.assert_not_called()
        # Should still emit at least one loop_pass_start.
        starts = [e for e in events if e.get("type") == "loop_pass_start"]
        self.assertEqual(len(starts), 1)

    # ----- Step 3: visual_inspect -----

    def test_visual_inspect_flags_empty_chart_svg(self):
        from pptx_agent.visual_inspect import inspect_slide_html
        html = """<html><body>
          <div class="block-chart"><svg class="chart-svg"></svg></div>
        </body></html>"""
        slide = {"blocks": [{"id": "x", "type": "chart", "props": {}}], "citations": []}
        findings = inspect_slide_html(html, slide)
        codes = {f.code for f in findings}
        self.assertIn("chart-empty-render", codes)

    def test_visual_inspect_passes_populated_table(self):
        from pptx_agent.visual_inspect import inspect_slide_html
        html = """<html><body>
          <div class="block-table"><table>
            <thead><tr><th>a</th><th>b</th></tr></thead>
            <tbody>
              <tr><td>1</td><td>2</td></tr>
              <tr><td>3</td><td>4</td></tr>
              <tr><td>5</td><td>6</td></tr>
            </tbody>
          </table></div>
        </body></html>"""
        slide = {"blocks": [{"id": "x", "type": "table", "props": {}}], "citations": []}
        findings = inspect_slide_html(html, slide)
        codes = {f.code for f in findings}
        self.assertNotIn("table-empty-render", codes)

    def test_visual_inspect_flags_text_density_overflow(self):
        from pptx_agent.visual_inspect import inspect_slide_html
        big = "x " * 800
        html = f"<html><body><div class='block-paragraph'><p>{big}</p></div></body></html>"
        slide = {"blocks": [{"id": "x", "type": "paragraph", "props": {}}], "citations": []}
        findings = inspect_slide_html(html, slide)
        codes = {f.code for f in findings}
        self.assertIn("density-too-high", codes)


    # ----- Edit flow: intent classifier + slide edit + per-slide rebuild -----

    def test_classify_intent_treats_no_job_as_new(self):
        from pptx_agent.intent import classify_intent
        out = classify_intent("change the chart on slide 3", has_active_job=False)
        self.assertEqual(out.intent, "new")

    def test_classify_intent_edit_with_slide_target_in_message(self):
        from pptx_agent.intent import classify_intent
        out = classify_intent(
            "change the chart on slide 3 to use 2024 data",
            has_active_job=True,
            active_slide_number=None,
        )
        self.assertEqual(out.intent, "edit")
        self.assertEqual(out.target_slide, 3)
        self.assertTrue(out.needs_research)

    def test_classify_intent_clarify_when_no_target(self):
        from pptx_agent.intent import classify_intent
        out = classify_intent(
            "change the color",
            has_active_job=True,
            active_slide_number=None,
        )
        self.assertEqual(out.intent, "clarify")

    def test_classify_intent_uses_active_slide_when_target_implicit(self):
        from pptx_agent.intent import classify_intent
        out = classify_intent(
            "make this slide brighter",
            has_active_job=True,
            active_slide_number=4,
        )
        self.assertEqual(out.intent, "edit")
        self.assertEqual(out.target_slide, 4)

    def test_classify_intent_strong_new_signal_beats_edit_verbs(self):
        from pptx_agent.intent import classify_intent
        out = classify_intent(
            "now make a new deck about climate change",
            has_active_job=True,
            active_slide_number=2,
        )
        self.assertEqual(out.intent, "new")

    def test_slide_edit_needs_research_regex(self):
        from pptx_agent.slide_edit import needs_research
        self.assertTrue(needs_research("add the latest 2024 numbers"))
        self.assertTrue(needs_research("cite more recent sources"))
        self.assertFalse(needs_research("make the title bigger"))

    def test_write_deck_artifacts_only_slides_skips_others(self):
        from pptx_agent.pipeline import write_deck_artifacts
        from pptx_agent.planner import build_deck
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = self.settings(root)
            research = Researcher(settings).run("briefing on solar", "solar")
            deck, _ = build_deck("briefing on solar", 5, research, settings)
            job_dir = root / "j-edit"
            write_deck_artifacts(deck, job_dir, research)
            # Snapshot mtimes for all per-slide HTML files.
            files = {n: (job_dir / f"slide-{n:02d}.html") for n in range(1, 6)}
            import time as _t
            mtimes_before = {n: p.stat().st_mtime_ns for n, p in files.items()}
            _t.sleep(0.02)
            # Re-render only slide 3.
            write_deck_artifacts(deck, job_dir, research, only_slides=[3])
            mtimes_after = {n: p.stat().st_mtime_ns for n, p in files.items()}
            for n in (1, 2, 4, 5):
                self.assertEqual(
                    mtimes_before[n], mtimes_after[n],
                    f"slide {n} html was rewritten despite only_slides=[3]",
                )
            self.assertGreater(mtimes_after[3], mtimes_before[3])


    # ----- fetch_url helper (full-page fetcher) -----

    def test_fetch_url_rejects_non_http_scheme(self):
        from pptx_agent.fetch import fetch_url
        out = fetch_url("ftp://example.com/x")
        self.assertTrue(out.startswith("[fetch_url error: only http/https"))

    def test_fetch_url_rejects_binary_extension(self):
        from pptx_agent.fetch import fetch_url
        out = fetch_url("https://example.com/report.pdf")
        self.assertTrue(out.startswith("[fetch_url: skipped binary extension"))

    def test_fetch_url_body_returns_tuple_on_error(self):
        from pptx_agent.fetch import fetch_url_body
        body, err = fetch_url_body("ftp://example.com/y")
        self.assertEqual(body, "")
        self.assertIsNotNone(err)
        self.assertIn("only http/https", err)

    def test_fetch_url_max_chars_truncates_and_prefixes(self):
        # Hit a deterministic local-style success path by mocking urlopen.
        from unittest import mock
        from pptx_agent.fetch import fetch_url

        class FakeHeaders:
            def get(self, key, default=""):
                if key.lower() == "content-type":
                    return "text/plain; charset=utf-8"
                return default

            def get_content_charset(self):
                return "utf-8"

        class FakeResp:
            status = 200
            headers = FakeHeaders()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return (b"alpha " * 500)[:n]

        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            out = fetch_url("https://example.com/page", max_chars=600)
        self.assertTrue(
            out.startswith("Full content from https://example.com/page:"),
            f"got: {out[:120]}",
        )
        self.assertIn("content truncated at 600 chars", out)


    # ----- Boilerplate / site-chrome filters -----

    def test_drop_boilerplate_strips_nav_and_cookie_lines(self):
        from pptx_agent.fetch import _drop_boilerplate
        raw = (
            "Sign in. Upload a document. "
            "Bangladesh's exports reached $46 billion in 2023, led by ready-made garments. "
            "0 ratings 0% found this document useful. Toggle navigation English. "
            "Read more Download free for 30 days. "
            "Total trade volume grew 12% over the prior year."
        )
        cleaned = _drop_boilerplate(raw)
        self.assertIn("exports reached $46 billion", cleaned)
        self.assertIn("trade volume grew 12%", cleaned)
        self.assertNotIn("Sign in", cleaned)
        self.assertNotIn("Toggle navigation", cleaned)
        self.assertNotIn("Download free", cleaned)
        self.assertNotIn("0 ratings", cleaned)

    def test_claim_miner_rejects_site_chrome_sentences(self):
        from pptx_agent.claim_miner import mine_claims
        research = {
            "sources": [{
                "source_id": "S1",
                "excerpt": (
                    "Read more Download free for 30 days. Sign in Upload Language EN. "
                    "Bangladesh exports reached $46 billion in 2023."
                ),
                "snippet": "",
            }],
            "insights": [],
        }
        claims = mine_claims(research)
        text_blob = " | ".join(c.text for c in claims).lower()
        self.assertNotIn("download free", text_blob)
        self.assertNotIn("toggle navigation", text_blob)
        self.assertNotIn("sign in upload", text_blob)
        # Real claim survives.
        self.assertTrue(any("$46 billion" in c.text for c in claims))

    def test_extract_slide_count_handles_page_synonym(self):
        from pptx_agent.planner import extract_slide_count
        self.assertEqual(extract_slide_count("build 10 page deck about X"), 10)
        self.assertEqual(extract_slide_count("Make a 7-page report"), 7)
        self.assertEqual(extract_slide_count("Create a 12-slide pitch"), 12)

    def test_extract_topic_strips_build_n_page(self):
        from pptx_agent.planner import extract_topic
        topic = extract_topic("Import export of Bangladesh in recent years, build 10 page")
        self.assertNotIn("build", topic.lower())
        self.assertNotIn("10 page", topic.lower())
        self.assertNotIn("10page", topic.lower())
        self.assertIn("bangladesh", topic.lower())

    def test_deck_audit_flags_title_that_looks_like_nav_boilerplate(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "T",
            "research": {"sources": []},
            "slides": [{
                "number": 3, "layout": "market", "citations": [],
                "title": "Read more Download 0 ratings 0% found this document useful",
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "y", "level": 1}},
                    {"type": "hero_stat", "props": {"value": "$46B", "label": "exports"}},
                ],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertIn("title-looks-like-site-chrome", codes)


    # ----- Analyst mode + topic alignment -----

    def test_deck_audit_flags_off_topic_slide(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "Bangladesh trade",
            "topic": "import export of Bangladesh in recent years",
            "research": {"sources": []},
            "slides": [{
                "number": 2, "layout": "solution",
                "title": "Best skincare routine for dry skin",
                "subtitle": "Daily face care tips.",
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "Skincare routine", "level": 1}},
                    {"type": "callout", "props": {"tone": "info", "text": "Moisturize daily"}},
                ],
                "bullets": ["Use a gentle cleanser", "Apply SPF 30 every morning"],
                "citations": [],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertIn("off-topic-slide", codes)

    def test_deck_audit_does_not_flag_on_topic_slide(self):
        from pptx_agent.deck_audit import audit_deck
        deck = {
            "title": "Bangladesh trade",
            "topic": "import export Bangladesh garments trade",
            "research": {"sources": []},
            "slides": [{
                "number": 2, "layout": "solution",
                "title": "Bangladesh ready-made garments exports lead trade",
                "subtitle": "Garments make up most Bangladesh exports.",
                "blocks": [
                    {"type": "eyebrow", "props": {"text": "x"}},
                    {"type": "heading", "props": {"text": "Bangladesh garment exports", "level": 1}},
                    {"type": "callout", "props": {"tone": "info", "text": "exports rose 12%"}},
                ],
                "bullets": ["Bangladesh garments grew 12% YoY"],
                "citations": [],
            }],
        }
        codes = {f["code"] for f in audit_deck(deck)["findings"]}
        self.assertNotIn("off-topic-slide", codes)

    def test_analyst_iter_emits_slide_authored_per_slide(self):
        from unittest.mock import MagicMock
        from pptx_agent.slide_author import iter_analyst_authoring_events
        # Patch analyst_pass via the module so the test stays cheap.
        from pptx_agent import analyst as _analyst

        def fake_analyst_pass(entry, *a, **kw):
            return {
                "number": int(entry["number"]),
                "id": f"slide-{entry['number']}",
                "layout": "solution",
                "title": f"Authored {entry['number']}",
                "subtitle": "",
                "eyebrow": "",
                "bullets": [],
                "metrics": [],
                "speaker_notes": "",
                "citations": [],
                "blocks": [{"id": "x", "type": "heading", "props": {"text": "x"}}],
                "accent_variant": 0,
            }
        original = _analyst.analyst_pass
        _analyst.analyst_pass = fake_analyst_pass
        try:
            outline = {"slides": [{"number": i, "role": "solution", "layout": "solution"}
                                  for i in range(1, 4)]}
            llm = MagicMock(spec=["complete_json"])
            events = list(iter_analyst_authoring_events(outline, {}, {}, llm, None))
            authored = [e for e in events if e.get("type") == "slide_authored"]
            self.assertEqual(len(authored), 3)
            self.assertEqual([a["number"] for a in authored], [1, 2, 3])
            self.assertEqual(events[-1]["type"], "slides_ready")
        finally:
            _analyst.analyst_pass = original


    # ----- html-ppt rendering shell -----

    def test_html_renderer_links_vendored_html_ppt_assets(self):
        from pptx_agent.html_renderer import render_single_slide_html
        deck = {
            "title": "T", "topic": "x", "theme": "betopia",
            "slides": [{
                "number": 1, "layout": "cover", "title": "Hello",
                "subtitle": "", "eyebrow": "", "citations": [],
                "bullets": [], "metrics": [],
                "blocks": [
                    {"id": "x", "type": "heading", "props": {"text": "Hello", "level": 1}},
                ],
            }],
        }
        html = render_single_slide_html(deck, deck["slides"][0])
        self.assertIn("/static/html-ppt/base.css", html)
        self.assertIn('id="theme-link"', html)
        self.assertIn("/static/html-ppt/themes/", html)
        self.assertIn("/static/html-ppt/token-bridge.css", html)
        self.assertIn("/static/html-ppt/runtime.js", html)
        self.assertIn("/static/html-ppt/animations/animations.css", html)

    def test_theme_bridge_aliases_legacy_names_to_html_ppt_files(self):
        from pptx_agent.themes import html_ppt_theme_filename
        self.assertEqual(html_ppt_theme_filename("betopia"), "soft-pastel.css")
        self.assertEqual(html_ppt_theme_filename("midnight"), "dracula.css")
        self.assertEqual(html_ppt_theme_filename("slate"), "corporate-clean.css")
        self.assertEqual(html_ppt_theme_filename("tokyo-night"), "tokyo-night.css")
        # Unknown name falls back to default's alias.
        out = html_ppt_theme_filename("does-not-exist")
        self.assertTrue(out.endswith(".css"))

    def test_block_render_carries_data_anim_when_prop_set(self):
        from pptx_agent.html_renderer import render_single_slide_html
        deck = {
            "title": "T", "topic": "x", "theme": "betopia",
            "slides": [{
                "number": 2, "layout": "metrics",
                "title": "Stats", "subtitle": "", "eyebrow": "",
                "citations": [], "bullets": [], "metrics": [],
                "animation": "fade-up",
                "blocks": [
                    {"id": "h", "type": "heading",
                     "props": {"text": "Stats", "level": 1}},
                    {"id": "m", "type": "hero_stat",
                     "props": {"value": "$15B", "label": "TAM", "anim": "zoom-in"}},
                ],
            }],
        }
        html = render_single_slide_html(deck, deck["slides"][0])
        self.assertIn('data-anim="fade-up"', html)
        self.assertIn('data-anim="zoom-in"', html)


if __name__ == "__main__":
    unittest.main()
