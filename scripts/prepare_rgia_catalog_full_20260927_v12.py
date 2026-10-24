"""Build the RGIA v12 per-query soft-ban-safe frozen package offline."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from prepare_rgia_catalog_full_20260926_v10 import FIXTURES, MODULES, SOURCE_TESTS, hashes


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/rgia_catalog_full_handoff_20260927_v12"
RUNNER = ROOT / "scripts/rgia_fullsweep_runner.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result


def scope() -> dict:
    sys.path.insert(0, str(ROOT / "scripts/modules"))
    from rgia_fullscope import KEYWORDS, TERRITORIES

    return {
        "source": "rgia",
        "scope_version": "20260927_294_v12_perquery_softban",
        "scope_origin": "output/prlib_catalog_full_handoff_20260918_v3/scope.json (49 territories)",
        "territories": [list(item) for item in TERRITORIES],
        "keywords": list(KEYWORDS),
        "year_from": 1700,
        "year_to": 1980,
        "simple_component_id": 72425,
        "tree_page_size": 12,
        "min_crawl_delay": 3,
        "max_get_per_invocation": 60,
        "transport_retry_backoff_seconds": [15, 45, 120],
        "transport_address_family": "AF_INET",
        "per_query_mode": True,
        "per_query_cooldown_seconds": 90,
        "soft_ban_backoff_seconds": [120, 300, 600],
        "soft_ban_max_consecutive": 3,
        "object_transport_attempts": 2,
        "module_sha256": sha(RUNNER),
        "record_level": "archival_case",
        "metadata_only": True,
        "ready_for_import": False,
        "csv_scalar_columns": 65,
    }


def instructions() -> str:
    return """# РГИА: public jstree v12, один запрос-поиск за заход

Пакет v12 продолжает только reduced scope `--gubernias-only`. При первом живом
запуске он копирует durable state и кандидатные записи v11 в новый output:
завершённый запрос 1 (`карта калужск`, 69 записей) не выполняется повторно.
Проверьте `MIGRATION_FROM_V11.json`: в нём должно быть `completed_queries: 1`.

Каждый запуск берёт ровно один следующий поисковый запрос и завершает его
exit 3 с рекомендованной паузой 90 секунд перед следующим запуском. В
`run_loop.ps1` эта пауза исполняется автоматически. Полный отказ host-стадий
robots/search/tree после ретраев 15/45/120 считается soft-ban: пакет не
повторяет GET в цикле, а задаёт hard-backoff 2, затем 5, затем 10 минут. После
трёх последовательных full-host failures он останавливается с exit 2 для
ручной проверки. Упорно недоступный отдельный объект после двух попыток
фиксируется в `object_transport_review`, получает `for_review=true`, а
запрос продолжает обработку следующих объектов.

Только HTTPS GET к `fgurgia.ru`; для соединения принудительно используется
IPv4. robots.txt обязателен, crawl-delay не меньше 3 секунд, бюджет — 60 GET
за запуск. Полный JSON карточки остаётся в `extra.raw_detail`; `downloadLink`
и `imageUrl` маппятся в поля 63 и 19. CSV-кандидат содержит 65 скалярных
полей. Все записи candidate, `ready_for_import=false`; Notion API и canonical
ontology не используются.

    powershell -ExecutionPolicy Bypass -File output/rgia_catalog_full_handoff_20260927_v12/run_loop.ps1
"""


def main() -> None:
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    tests = checked(
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
  & python -B 'output/rgia_catalog_full_handoff_20260927_v12/run_catalog.py' --gubernias-only
  $exitCode = $LASTEXITCODE
  if ($exitCode -eq 0) { break }
  if ($exitCode -ne 3) { break }
  $attempt = Get-ChildItem 'output/rgia_catalog_full_20260927_v12_gubernias/attempts' -Directory |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
  $report = Get-Content -Raw -LiteralPath (Join-Path $attempt.FullName 'REPORT.json') | ConvertFrom-Json
  $seconds = [int]$report.next_invocation_delay_seconds
  if ($seconds -lt 1) { $seconds = 90 }
  Start-Sleep -Seconds $seconds
}
exit $exitCode
""",
        encoding="utf-8",
    )
    manifest = {
        "package": "rgia_catalog_full_handoff_20260927_v12",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"base_url": "https://fgurgia.ru", "network": "not_run"},
        "query_model": "public_jstree_case_list_nPage_294_v12_perquery_softban",
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "fixtures": {source.name: sha(fixtures / source.name) for source in FIXTURES},
        "continuation": {
            "working_output": "output/rgia_catalog_full_20260927_v12",
            "working_output_gubernias": "output/rgia_catalog_full_20260927_v12_gubernias",
            "prior_package": "output/rgia_catalog_full_handoff_20260926_v11",
            "migration_from_gubernias": "output/rgia_catalog_full_20260926_v11_gubernias",
            "state_migration": "copy_v11_durable_records_and_query_state_once",
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify = checked(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('v12', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(OUT / "run_catalog.py"),
        ],
        ROOT,
    )
    regression = checked(
        [sys.executable, "-B", "-m", "pytest", "test_rgia_fullsweep_v12.py", "-q"],
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
