"""Build the independent frozen RGADA full-inventory catalog v2, offline."""

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/rgada_catalog_full_handoff_20260921_v2"
FIXTURES = ROOT / "output/rgada_fixtures_2026-09-21"
RUNNER = ROOT / "scripts/rgada_catalog_full_runner.py"
SOURCE_SCOPE = ROOT / "output/prlib_catalog_full_handoff_20260920_v6/scope.json"
MODULES = ("classify_stop.py", "durable_state.py", "scrapers/searcher_rgada.py")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scope():
    value = json.loads(SOURCE_SCOPE.read_text(encoding="utf-8"))
    value.update(
        source="rgada",
        search_fields=["list_name", "fund_name"],
        Sk=30,
        record_level="archival_inventory",
        cards_within_inventory="not_collected",
        related_cases="deferred",
        ready_for_import=False,
    )
    return value


def instructions():
    return """# РГАДА — полный проход метаданных описей v1

Пакет создаёт **новый** output `output/rgada_catalog_full_20260921_v2/`; это не продолжение ПрБ. Единица результата — **опись**, а не дело и не отдельная карта. Сведения о картах внутри описей требуют самостоятельного последующего шага.

1. Запустить только `python -B output/rgada_catalog_full_handoff_20260921_v2/run_catalog.py`.
2. Единственные допускаемые GET: `http://rgada.info/robots.txt` и `http://rgada.info/poisk/index.php` с `list_name` или `fund_name`, `Sk=30`, при необходимости `page=N`. HTTPS, PDF, карточки, POST, cookies, proxy/VPN и redirect не используются.
3. Перед поиском проверяется robots.txt; crawl-delay соблюдается. robots_disallow, CAPTCHA, real_barrier, redirect-login, транспорт после внутренней политики, request_budget и JSONL/CSV mismatch фатальны.
4. `repeated_page`, pager/classifier mismatch и локальная неподтверждённая пустота получают `partial` + `for_review`; уже записанные строки сохраняются, следующий запрос продолжается. `repeated_page` не является концом выдачи.
5. `atomic_json` общего v6-слоя делает до 8 попыток только для PermissionError/WinError 5/32. Пакет ведёт sealed run_scope, state/lock, REPORT и SHA-256 manifest.

Весь результат — candidate; `ready_for_import=false`. Изображения, OCR, связанные дела, Notion и canonical-онтология не входят в запуск. После `query_scope_review`, барьера или любой фатальной остановки передать человеку последний `REPORT.json`.
"""


def main():
    if OUT.exists():
        raise SystemExit("Refusing to overwrite existing package: " + str(OUT))
    if not FIXTURES.is_dir() or not RUNNER.is_file():
        raise SystemExit("Missing RGADA fixtures or runner")
    tests = subprocess.run(
        [sys.executable, "-B", "-m", "pytest"],
        cwd=ROOT / "tests",
        text=True,
        capture_output=True,
    )
    if tests.returncode:
        sys.stdout.write(tests.stdout)
        sys.stderr.write(tests.stderr)
        raise SystemExit("Local tests failed; RGADA package was not created")
    (OUT / "frozen/scripts/modules/scrapers").mkdir(parents=True)
    for rel in MODULES:
        shutil.copy2(
            ROOT / "scripts/modules" / rel, OUT / "frozen/scripts/modules" / rel
        )
    (OUT / "fixtures").mkdir()
    for item in json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8")):
        shutil.copy2(
            FIXTURES / (item["label"] + ".html"),
            OUT / "fixtures" / (item["label"] + ".html"),
        )
    shutil.copy2(FIXTURES / "robots.txt", OUT / "fixtures/robots.txt")
    shutil.copy2(
        FIXTURES / "robots_RAW_bytes.txt", OUT / "fixtures/robots_RAW_bytes.txt"
    )
    shutil.copy2(FIXTURES / "manifest.json", OUT / "fixtures/manifest.json")
    (OUT / "scope.json").write_text(
        json.dumps(scope(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    runner_text = RUNNER.read_text(encoding="utf-8").replace(
        "rgada_catalog_full_20260921_v1", "rgada_catalog_full_20260921_v2"
    )
    (OUT / "run_catalog.py").write_text(runner_text, encoding="utf-8")
    (OUT / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8")
    loop = """$ErrorActionPreference = "Continue"\n$root = "D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив"\nSet-Location $root\n$outDir = "$root\\output\\rgada_catalog_full_20260921_v2"\nfor ($i = 1; $i -le 60; $i++) {\n    & python -B "output/rgada_catalog_full_handoff_20260921_v2/run_catalog.py"\n    $code = $LASTEXITCODE\n    if ($code -ne 3) { break }\n    Start-Sleep -Seconds 5\n}\n"""
    (OUT / "run_loop.ps1").write_text(loop, encoding="utf-8")
    project_files = {
        p.relative_to(OUT / "frozen").as_posix(): sha(p)
        for p in sorted((OUT / "frozen").rglob("*"))
        if p.is_file()
    }
    package_files = {
        p.relative_to(OUT).as_posix(): sha(p)
        for p in sorted(OUT.rglob("*"))
        if p.is_file() and "frozen" not in p.parts
    }
    manifest = {
        "project_files": project_files,
        "package_files": package_files,
        "dependencies": {
            "beautifulsoup4": "4.14.3",
            "soupsieve": "2.8.3",
            "requests": "2.33.1",
            "lxml": "6.0.2",
        },
        "continuation": {
            "working_output": "output/rgada_catalog_full_20260921_v2",
            "scope_sha256": sha(OUT / "scope.json"),
            "accepted_prior_module_hashes": [],
            "prior_package": "output/rgada_catalog_full_handoff_20260921_v1",
            "state_migration": "not_required_v1_output_has_no_query_state",
        },
        "source": {
            "base_url": "http://rgada.info/",
            "record_level": "archival_inventory",
            "network": "not_run",
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    check = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib.util; p=r'"
            + str(OUT / "run_catalog.py")
            + "'; s=importlib.util.spec_from_file_location('rgada_v1',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.verify())",
        ],
        text=True,
        capture_output=True,
    )
    if check.returncode or check.stdout.strip() != "True":
        shutil.rmtree(OUT)
        raise SystemExit("Frozen verification failed: " + check.stderr + check.stdout)
    validation = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "not_run",
        "local_pytest_exit_code": 0,
        "local_pytest_summary": next(
            (
                line.strip()
                for line in reversed(tests.stdout.splitlines())
                if "passed" in line
            ),
            "unknown",
        ),
        "frozen_verify": True,
        "manifest_sha256": sha(OUT / "manifest.json"),
        "fixtures_manifest_sha256": sha(OUT / "fixtures/manifest.json"),
        "record_level": "archival_inventory",
        "query_local_review_reasons": [
            "repeated_page",
            "pager_classifier_mismatch",
            "empty_without_end_marker",
        ],
        "depth_cap": "not_enabled",
        "request_budget": 500,
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
