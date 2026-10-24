"""Offline tests for the NEB recon-first package contract."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/neb_recon_handoff_20260928_v3"


def runner():
    spec = importlib.util.spec_from_file_location("neb_recon_v1", PACKAGE / "run_recon.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_neb_recon_contract_is_small_and_has_no_field_parser():
    module = runner()
    assert module.REQUEST_BUDGET == 3
    assert "parse" not in module.run.__name__
    assert module.catalog_url_from_html('<a href="/catalog/a/">A</a>') == "https://rusneb.ru/catalog/a/"
    assert module.catalog_url_from_html('<a href="https://other.example/catalog/a/">A</a>') is None


def test_neb_recon_robots_gate_blocks_search_when_disallowed():
    module = runner()
    robots = "User-agent: *\nDisallow: /search/\n"
    assert not module.robots_allows(robots, module.SEARCH_URL)


def test_neb_recon_marks_challenge_without_parsing_it_as_a_card():
    module = runner()
    assert module.has_block_signal(403, "<html>Just a moment</html>")
