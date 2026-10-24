"""Offline contract checks for the frozen NEB full-sweep package."""
from __future__ import annotations

import importlib.util
import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/neb_catalog_full_handoff_20260929_v3_1"


def runner():
    for name in ("notion_export", "neb_notion", "neb_card_dom"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("neb_full_v1", PACKAGE / "run_catalog.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_neb_full_scope_and_search_no_pagination_parameter():
    module = runner()
    assert len(module.TARGET_GUBERNIAS) * len(module.KEYWORDS) == 24
    assert "page=" not in module._search_url("карта Калужская губерния")
    assert "pagen=" not in module._search_url("карта Калужская губерния").casefold()


def test_neb_scopes_catalog_links_and_parses_explicit_total():
    module = runner()
    html = """<a href='/catalog/outside/'>outside</a><section class='search-result'>
    <a href='/catalog/one/'>one</a><a href='/catalog/one/'>duplicate</a></section>
    <div>Найдено 131 результат</div>"""
    assert module._catalog_links(html) == ["https://rusneb.ru/catalog/one/"]
    assert module._result_total(html) == 131


def test_neb_card_parser_preserves_map_classifier_and_file_url():
    module = runner()
    raw = (ROOT / "output/neb_recon_20260928_v1/raw_html/card_map_rendered.html").read_text(encoding="utf-8")
    value = module.parse_card(raw, "https://rusneb.ru/catalog/000199_000009_008725490/")
    assert value["is_map"]
    assert "карт" in value["catalog_raw"].casefold()
    assert value["viewer_url"].endswith("/viewer/")


def test_neb_frozen_startup_loads_all_local_resources():
    runner()
    frozen_modules = PACKAGE / "frozen/scripts/modules"
    for name in ("cartographic_enrichment", "notion_export", "neb_notion", "administrative_level", "library_dates"):
        sys.modules.pop(name, None)
    cartography = importlib.import_module("cartographic_enrichment")
    exporter = importlib.import_module("notion_export")
    for name in ("neb_notion", "administrative_level", "library_dates"):
        imported = importlib.import_module(name)
        assert Path(imported.__file__).parent == frozen_modules
    assert cartography.VOCAB_PATH == frozen_modules / "object_types.json"
    assert json.loads(cartography.VOCAB_PATH.read_text(encoding="utf-8"))["version"]
    assert exporter.SCHEMA_PATH == frozen_modules / "notion_schema.json"
    assert json.loads(exporter.SCHEMA_PATH.read_text(encoding="utf-8"))["version"]
