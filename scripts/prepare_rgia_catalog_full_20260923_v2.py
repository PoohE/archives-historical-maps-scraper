"""Build the immutable 294-query RGIA full-sweep package without network."""

from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/rgia_catalog_full_handoff_20260923_v2"
RUNNER = ROOT / "scripts/rgia_fullsweep_runner.py"
MODULES = (
    "classify_stop.py",
    "durable_state.py",
    "notion_export.py",
    "rgia_notion.py",
    "library_dates.py",
    "cartographic_enrichment.py",
    "administrative_level.py",
    "object_types.json",
    "notion_schema.json",
    "rgia_fullscope.py",
    "scrapers/searcher_rgia.py",
)
TESTS = (
    "test_rgia_fullscope.py",
    "test_rgia_ajax_tree.py",
    "test_rgia_detail_notion_gate_v4.py",
)
FIXTURES = (
    ROOT / "output/rgia_fixtures_2026-09-22/live_WORKING_karta_kaluzhsk.html",
    ROOT / "output/rgia_fixtures_2026-09-22/robots_RAW_bytes.txt",
    ROOT / "output/rgia_fixtures_2026-09-22/manifest.json",
    ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json",
)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def hashes(base):
    return {
        p.relative_to(base).as_posix(): sha(p)
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }


def scope():
    sys.path.insert(0, str(ROOT / "scripts/modules"))
    from rgia_fullscope import TERRITORIES, KEYWORDS

    return {
        "source": "rgia",
        "scope_version": "20260923_294_v1",
        "scope_origin": "output/prlib_catalog_full_handoff_20260918_v3/scope.json (49 territories)",
        "territories": [list(x) for x in TERRITORIES],
        "keywords": list(KEYWORDS),
        "year_from": 1700,
        "year_to": 1980,
        "simple_component_id": 72425,
        "tree_page_size": 12,
        "min_crawl_delay": 3,
        "max_get_per_invocation": 60,
        "module_sha256": sha(RUNNER),
        "record_level": "archival_case",
        "metadata_only": True,
        "ready_for_import": False,
    }


def instructions():
    return """# РГИА: полный public jstree sweep — 294 запроса

Full scope: 49 retained territorial formulations x 6 keywords = 294. It is
frozen from the accepted prior 49-territory scope, not implicitly expanded to
the later 54-item territories.py list. Each query is:
GET robots.txt -> GET /search -> GET jstree root and all case pages -> GET
/ajax/obj detail for each case. The unit is an archival case. Keywords remain
in the full-text query. Dates are filtered only where parsed; candidate rows
are exported locally to 66 scalar CSV fields.

First reduced run (four губерния queries x six keywords = 24):
    python -B output/rgia_catalog_full_handoff_20260923_v2/run_catalog.py --gubernias-only

Canonical full run:
    python -B output/rgia_catalog_full_handoff_20260923_v2/run_catalog.py

Only HTTPS GET to fgurgia.ru is permitted. One clean in-memory session is used
per invocation; no cookie is logged. robots.txt plus crawl-delay (>=3 sec)
are mandatory. The invocation budget is 60 GET; exit 3 means request_budget
and only that can be continued by run_loop.ps1. Each transport GET receives at
most two delayed retries; failure after them, a barrier, redirect, robots
failure, integrity error or an unverified stop ends the run for a human.

Forbidden: POST/forms, login/auth, CAPTCHA workaround, proxy/VPN, headless,
requests outside the frozen scope, Notion API and canonical ontology writes.
All output remains candidate, ready_for_import=false. On any nonzero result,
return its REPORT.json, coverage.json and requests.jsonl; do not auto-repeat
a fatal result.
"""


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    tests = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", *TESTS, "-q"],
        cwd=ROOT / "tests",
        text=True,
        capture_output=True,
    )
    if tests.returncode:
        raise RuntimeError(tests.stdout + "\n" + tests.stderr)
    frozen = OUT / "frozen/scripts/modules"
    (frozen / "scrapers").mkdir(parents=True)
    for rel in MODULES:
        target = frozen / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/modules" / rel, target)
    shutil.copy2(RUNNER, OUT / "run_catalog.py")
    fixtures = OUT / "fixtures"
    fixtures.mkdir()
    for src in FIXTURES:
        shutil.copy2(src, fixtures / src.name)
    (OUT / "scope.json").write_text(
        json.dumps(scope(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8")
    (OUT / "run_loop.ps1").write_text(
        """$ErrorActionPreference = 'Continue'
$root = 'D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив'
Set-Location $root
$outDir = Join-Path $root 'output\\rgia_catalog_full_20260923_v2_gubernias'
for ($i = 1; $i -le 100; $i++) {
  & python -B 'output/rgia_catalog_full_handoff_20260923_v2/run_catalog.py' --gubernias-only
  if ($LASTEXITCODE -ne 3) { break }
  $report = Get-ChildItem (Join-Path $outDir 'attempts') -Directory | Sort-Object Name -Descending | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName 'REPORT.json' }
  if (-not $report -or (Get-Content -Raw $report | ConvertFrom-Json).stop_reason -ne 'request_budget') { break }
  Start-Sleep -Seconds 5
}
""",
        encoding="utf-8",
    )
    m = {
        "package": "rgia_catalog_full_handoff_20260923_v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"base_url": "https://fgurgia.ru", "network": "not_run"},
        "query_model": "public_jstree_case_list_294_v1",
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "fixtures": {p.name: sha(fixtures / p.name) for p in FIXTURES},
        "continuation": {
            "working_output": "output/rgia_catalog_full_20260923_v2",
            "working_output_gubernias": "output/rgia_catalog_full_20260923_v2_gubernias",
            "prior_package": "output/rgia_catalog_full_handoff_20260923_v1",
            "state_migration": "not_applicable_new_294_query_scope",
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    check = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib.util;p=importlib.util.spec_from_file_location('x',r'{}');m=importlib.util.module_from_spec(p);p.loader.exec_module(m);assert m.verify()".format(
                OUT / "run_catalog.py"
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if check.returncode:
        raise RuntimeError(check.stdout + check.stderr)
    val = {
        "network": "not_run",
        "source_tests": next(
            (x for x in reversed(tests.stdout.splitlines()) if "passed" in x), "unknown"
        ),
        "frozen_verify": True,
        "manifest_sha256": sha(OUT / "manifest.json"),
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(
        json.dumps(val, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(val, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
