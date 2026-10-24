"""Build the RGIA v13 intra-query-checkpoint frozen package offline."""

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
OUT = ROOT / "output/rgia_catalog_full_handoff_20260929_v13_5"
RUNNER = ROOT / "scripts/rgia_fullsweep_runner_v135.py"


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
        "scope_version": "20260929_294_v13_intraquery_checkpoint",
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
        "intraquery_checkpoint": True,
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
    return """# РГИА: public jstree v13.5, внутрикверийный checkpoint

Пакет v13 продолжает только reduced scope `--gubernias-only`. При первом живом
запуске он копирует durable state и кандидатные записи v13.3 в новый output:
три завершённых запроса не выполняются повторно. Неполный запрос
`Калужская губерния|съёмка|rgia` сбрасывается к tree page 1, чтобы применить
фикс пустого дерева. Проверьте `MIGRATION_FROM_V13_3.json`: в нём должны быть
`completed_queries: 3`, `migrated_records: 1660` и reset-ключ запроса.

Каждый запуск продолжает ровно один следующий поисковый запрос. Курсоры
`next_tree_page` и `next_detail_index`, а также накопленный `object_ids`,
сохраняются после каждой страницы и карточки. Если partial-заход не сдвинул
ни один курсор, пакет останавливается с `no_forward_progress` и exit 2.
Полный отказ host-стадий
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

    bash output/rgia_catalog_full_handoff_20260929_v13_5/run_loop.sh
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
    (OUT / "run_loop.sh").write_text("""#!/usr/bin/env bash
set -u
for i in $(seq 1 100); do
  python -B output/rgia_catalog_full_handoff_20260929_v13_5/run_catalog.py --gubernias-only
  code=$?
  [ "$code" -eq 3 ] || exit "$code"
  sleep 90
done
exit 3
""", encoding="utf-8")
    manifest = {
        "package": "rgia_catalog_full_handoff_20260929_v13_5",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"base_url": "https://fgurgia.ru", "network": "not_run"},
        "query_model": "public_jstree_case_list_nPage_294_v13_intraquery_checkpoint",
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "fixtures": {source.name: sha(fixtures / source.name) for source in FIXTURES},
        "continuation": {
            "working_output": "output/rgia_catalog_full_20260929_v13_5",
            "working_output_gubernias": "output/rgia_catalog_full_20260929_v13_5_gubernias",
            "prior_package": "output/rgia_catalog_full_handoff_20260929_v13_3",
            "migration_from_gubernias": "output/rgia_catalog_full_20260929_v13_3_gubernias",
            "state_migration": "copy_v13_3_durable_records_preserve_reported_end_reset_cases_root_missing_once",
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
            "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('v13', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(OUT / "run_catalog.py"),
        ],
        ROOT,
    )
    regression = checked(
        [sys.executable, "-B", "-m", "pytest", "test_rgia_fullsweep_v135.py", "-q"],
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
