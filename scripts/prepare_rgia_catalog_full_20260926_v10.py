"""Build the RGIA v10 slow-drain frozen package without network access."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/rgia_catalog_full_handoff_20260926_v10"
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
FIXTURES = (
    ROOT / "output/rgia_fixtures_2026-09-22/live_WORKING_karta_kaluzhsk.html",
    ROOT / "output/rgia_fixtures_2026-09-22/robots_RAW_bytes.txt",
    ROOT / "output/rgia_fixtures_2026-09-22/manifest.json",
    ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json",
)
SOURCE_TESTS = (
    "test_adapters_v16.py",
    "test_rgia_fullscope.py",
    "test_rgia_ajax_tree.py",
    "test_rgia_detail_classification_v5.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(base: Path) -> dict[str, str]:
    return {
        path.relative_to(base).as_posix(): sha(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def scope() -> dict:
    sys.path.insert(0, str(ROOT / "scripts/modules"))
    from rgia_fullscope import KEYWORDS, TERRITORIES

    return {
        "source": "rgia",
        "scope_version": "20260926_294_v10",
        "scope_origin": "output/prlib_catalog_full_handoff_20260918_v3/scope.json (49 territories)",
        "territories": [list(item) for item in TERRITORIES],
        "keywords": list(KEYWORDS),
        "year_from": 1700,
        "year_to": 1980,
        "simple_component_id": 72425,
        "tree_page_size": 12,
        "min_crawl_delay": 15,
        "max_get_per_invocation": 12,
        "transport_retry_backoff_seconds": [15, 45, 120],
        "module_sha256": sha(RUNNER),
        "record_level": "archival_case",
        "metadata_only": True,
        "ready_for_import": False,
        "csv_scalar_columns": 65,
    }


def instructions() -> str:
    return """# РГИА: public jstree slow-drain v10

Пакет v10 предназначен для нового самостоятельного reduced/full run; не
подменяет и не продолжает output v9. Scope: 49 территориальных формулировок ×
6 ключевых слов; первый запуск `--gubernias-only` содержит 24 запроса.

Только HTTPS GET к `fgurgia.ru`. robots.txt обязателен. Интервал не меньше
15 секунд; за один запуск не больше 12 GET. На сетевой сбой применяются три
отложенные попытки 15/45/120 секунд. После исчерпания попыток результат —
partial stop с exit 3: durable state и `query_progress.json` сохраняются, а
`next_query` явно показывает следующий незавершённый запрос.

Карточка сохраняется полностью: `record.extra.raw_detail` содержит исходный
JSON detail; `downloadLink` и `imageUrl`, если источник их отдаёт, маппятся в
поля 63 и 19. CSV-кандидат содержит 65 скалярных полей, включая «Год
сканирования». Все результаты candidate, `ready_for_import=false`; Notion API
и canonical ontology не используются.

Проверочный reduced запуск:

    python -B output/rgia_catalog_full_handoff_20260926_v10/run_catalog.py --gubernias-only

Продолжение только после exit 3:

    pwsh output/rgia_catalog_full_handoff_20260926_v10/run_loop.ps1
"""


def run_checked(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(completed.stdout + "\n" + completed.stderr)
    return completed


def main() -> None:
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    tests = run_checked(
        [sys.executable, "-B", "-m", "pytest", *SOURCE_TESTS, "-q"], ROOT / "tests"
    )
    frozen = OUT / "frozen/scripts/modules"
    (frozen / "scrapers").mkdir(parents=True)
    for rel in MODULES:
        target = frozen / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/modules" / rel, target)
    shutil.copy2(RUNNER, OUT / "run_catalog.py")
    fixtures = OUT / "fixtures"
    fixtures.mkdir()
    for source in FIXTURES:
        shutil.copy2(source, fixtures / source.name)
    (OUT / "scope.json").write_text(
        json.dumps(scope(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8")
    (OUT / "run_loop.ps1").write_text(
        """$ErrorActionPreference = 'Continue'
$root = 'D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив'
Set-Location $root
for ($i = 1; $i -le 100; $i++) {
  & python -B 'output/rgia_catalog_full_handoff_20260926_v10/run_catalog.py' --gubernias-only
  if ($LASTEXITCODE -ne 3) { break }
  Start-Sleep -Seconds 90
}
""",
        encoding="utf-8",
    )
    manifest = {
        "package": "rgia_catalog_full_handoff_20260926_v10",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"base_url": "https://fgurgia.ru", "network": "not_run"},
        "query_model": "public_jstree_case_list_nPage_294_v10_slow_drain",
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "fixtures": {source.name: sha(fixtures / source.name) for source in FIXTURES},
        "continuation": {
            "working_output": "output/rgia_catalog_full_20260926_v10",
            "working_output_gubernias": "output/rgia_catalog_full_20260926_v10_gubernias",
            "prior_package": "output/rgia_catalog_full_handoff_20260923_v9",
            "state_migration": "not_applicable: independent v10 scope and capture contract",
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify = run_checked(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('v10', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(OUT / "run_catalog.py"),
        ],
        ROOT,
    )
    regression = run_checked(
        [sys.executable, "-B", "-m", "pytest", "test_rgia_fullsweep_v10.py", "-q"],
        ROOT / "tests",
    )
    validation = {
        "network": "not_run",
        "source_tests": next(
            (line for line in reversed(tests.stdout.splitlines()) if "passed" in line), "unknown"
        ),
        "frozen_verify": bool(verify),
        "frozen_regression": next(
            (line for line in reversed(regression.stdout.splitlines()) if "passed" in line), "unknown"
        ),
        "manifest_sha256": sha(OUT / "manifest.json"),
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
