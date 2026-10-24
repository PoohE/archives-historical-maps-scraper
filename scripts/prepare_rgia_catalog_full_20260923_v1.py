"""Build frozen full RGIA jstree package offline; do not run network."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260923_v1"
RUNNER = ROOT / "scripts/rgia_catalog_full_runner.py"
MODULES = (
    "notion_export.py", "rgia_notion.py", "library_dates.py",
    "cartographic_enrichment.py", "administrative_level.py", "object_types.json",
    "notion_schema.json", "scrapers/searcher_rgia.py",
)
FIXTURES = (
    "live_WORKING_karta_kaluzhsk.html", "robots_RAW_bytes.txt", "manifest.json",
)
TESTS = (
    "test_rgia_saved.py", "test_rgia_ajax_tree.py",
    "test_rgia_detail_notion_gate_v4.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(base: Path) -> dict[str, str]:
    return {
        item.relative_to(base).as_posix(): sha(item)
        for item in sorted(base.rglob("*"))
        if item.is_file()
    }


def scope() -> dict:
    return {
        "source": "rgia",
        "record_level": "archival_case",
        "query": "карта калужск",
        "query_human": "карта Калужская губерния",
        "simple_component_id": 72425,
        "tree_page_size": 12,
        "fallback_crawl_delay": 3,
        "max_get_per_invocation": 100,
        "expected_cases_observed": 74,
        "metadata_only": True,
        "forms_or_post": False,
        "authentication": False,
        "captcha_bypass": False,
        "vpn_or_proxy": False,
        "headless": False,
        "notion_or_canonical_ontology": False,
        "ready_for_import": False,
    }


def instructions() -> str:
    return """# РГИА — полный публичный jstree-обход дел v1

Пакет основан на принятой цепочке GET: robots.txt -> /search (карта калужск)
-> /ajax/tree/{search_index} (root и Дела для каждой tree-страницы)
-> /ajax/obj/{object_id}/{search_index}?children=false. Один чистый
requests-сеанс сохраняет серверный контекст только в памяти; cookies не
логируются и не записываются.

Запуск (только после отдельного решения)::
    python -B output/rgia_catalog_full_handoff_20260923_v1/run_catalog.py

Перед первым GET проверяются frozen-хеши. Соблюдаются robots.txt и crawl-delay
(не менее 3 секунд); разрешены только HTTPS GET к fgurgia.ru. Бюджет 100 GET
покрывает наблюдаемые 74 дела (ожидаемо до 84 GET), но не расширяет scope.

Не отправлять формы/POST, не авторизоваться, не обходить CAPTCHA/robots,
не применять proxy/VPN/headless, не запрашивать карточки вне 74 дел, не
записывать в Notion или canonical ontology. Барьер, redirect, robots-disallow,
транспорт, budget, несогласованность JSONL/CSV или manifest -- остановка
человеку. Результаты -- candidate; 66-польный CSV создаётся только локально,
ready_for_import=false.
"""


def main() -> int:
    if PACKAGE.exists():
        raise FileExistsError("Refusing to overwrite package: " + str(PACKAGE))
    tests = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", *TESTS, "-q"],
        cwd=ROOT / "tests", text=True, capture_output=True,
    )
    if tests.returncode:
        raise RuntimeError(tests.stdout + "\n" + tests.stderr)
    frozen_modules = PACKAGE / "frozen/scripts/modules"
    (frozen_modules / "scrapers").mkdir(parents=True)
    for rel in MODULES:
        target = frozen_modules / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/modules" / rel, target)
    shutil.copy2(RUNNER, PACKAGE / "run_catalog.py")
    fixture_dir = PACKAGE / "fixtures"
    fixture_dir.mkdir()
    source_fixtures = ROOT / "output/rgia_fixtures_2026-09-22"
    for name in FIXTURES:
        shutil.copy2(source_fixtures / name, fixture_dir / name)
    (PACKAGE / "scope.json").write_text(
        json.dumps(scope(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (PACKAGE / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8")
    manifest = {
        "package": "rgia_catalog_full_handoff_20260923_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"base_url": "https://fgurgia.ru", "network": "not_run"},
        "query_model": "public_jstree_case_list_v1",
        "project_files": hashes(PACKAGE / "frozen"),
        "package_files": hashes(PACKAGE),
        "fixtures": {name: sha(fixture_dir / name) for name in FIXTURES},
        "continuation": {
            "working_output": "output/rgia_catalog_full_20260923_v1",
            "prior_evidence": "output/rgia_detail_notion_gate_20260923_v4",
            "state_migration": "not_applicable_new_full_scope",
        },
    }
    (PACKAGE / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify = subprocess.run(
        [sys.executable, "-B", "-c",
         "import importlib.util; p=importlib.util.spec_from_file_location('r', r'{}'); m=importlib.util.module_from_spec(p); p.loader.exec_module(m); assert m.verify()".format(PACKAGE / "run_catalog.py")],
        cwd=ROOT, text=True, capture_output=True,
    )
    if verify.returncode:
        raise RuntimeError("frozen verify failed\n" + verify.stdout + verify.stderr)
    result = {
        "network": "not_run",
        "local_pytest_exit_code": tests.returncode,
        "local_pytest_summary": next(
            (line.strip() for line in reversed(tests.stdout.splitlines()) if "passed" in line),
            "unknown",
        ),
        "frozen_verify": True,
        "manifest_sha256": sha(PACKAGE / "manifest.json"),
    }
    (PACKAGE / "LOCAL_VALIDATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
