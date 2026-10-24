"""Build the frozen RGADA v3 territory-term catalog package offline."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/rgada_catalog_full_handoff_20260922_v3"
FIXTURES = ROOT / "output/rgada_fixtures_2026-09-21"
RUNNER = ROOT / "scripts/rgada_catalog_full_runner.py"
MODULES = ("classify_stop.py", "durable_state.py", "scrapers/searcher_rgada.py")
TESTS = (
    "test_rgada_catalog_v1.py",
    "test_rgada_robots_raw.py",
    "test_rgada_v1_frozen.py",
    "test_rgada_v2_frozen.py",
    "test_rgada_query_model_v3.py",
)
KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж", "топографическая"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scope():
    return {
        "source": "rgada",
        "query_model": "territory_single_term_local_keyword_filter_v1",
        "territories": [
            {"label": "Калужская губерния", "search_term": "Калужск"},
            {"label": "Пермская губерния", "search_term": "Перм"},
            {"label": "Смоленская губерния", "search_term": "Смоленск"},
            {"label": "Ярославская губерния", "search_term": "Ярославск"},
        ],
        "keywords": KEYWORDS,
        "search_fields": ["list_name", "fund_name"],
        "Sk": 30,
        "year_from": 1700,
        "year_to": 1980,
        "max_get_per_invocation": 500,
        "record_level": "archival_inventory",
        "metadata_only": True,
        "images_ocr": "deferred",
        "related_cases": "deferred",
        "corpus_completeness": "not_established",
        "ready_for_import": False,
    }


def instructions():
    return """# РГАДА — полный проход метаданных описей v3

Это новый output output/rgada_catalog_full_20260922_v3. Модель запросов РГАДА
отличается от ПрБ и РГИА: сайт сопоставляет одну цельную подстроку в одном поле,
а не слова с логикой И.

Для каждой из четырёх территорий единственный search_term (Калужск, Перм,
Смоленск, Ярославск) отправляется отдельно в list_name и fund_name. Слова
карта, план, атлас, съёмка, чертёж и топографическая не добавляются в URL:
они локально проверяются в названии фонда, названии описи и аннотации
полученных строк. Пагинация fund_name продолжается по page=N до штатного
конца или isolated review.

Запуск: python -B output/rgada_catalog_full_handoff_20260922_v3/run_catalog.py

Допустимы только GET http://rgada.info/robots.txt и
http://rgada.info/poisk/index.php с list_name или fund_name, Sk=30 и page=N.
Не применять HTTPS, PDF, карточки, POST, cookies, VPN/прокси, авторизацию,
CAPTCHA, Notion, canonical ontology, OCR или headless. Барьер, robots_disallow,
CAPTCHA, transport после retry, request_budget и целостность — фатальны.
repeated_page и pager-анома-лии одного query — partial/for_review.

Результат — candidate-описи, не дела и не доказанный корпус карт;
ready_for_import=false.
"""


def hashes(base):
    return {
        path.relative_to(base).as_posix(): sha(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def main():
    if OUT.exists():
        raise SystemExit("Refusing to overwrite existing package: " + str(OUT))
    tests = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", *TESTS, "-q"],
        cwd=ROOT / "tests",
        text=True,
        capture_output=True,
    )
    if tests.returncode:
        sys.stdout.write(tests.stdout)
        sys.stderr.write(tests.stderr)
        raise SystemExit("RGADA v3 local tests failed; package not created")
    (OUT / "frozen/scripts/modules/scrapers").mkdir(parents=True)
    for rel in MODULES:
        target = OUT / "frozen/scripts/modules" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/modules" / rel, target)
    shutil.copy2(RUNNER, OUT / "run_catalog.py")
    (OUT / "fixtures").mkdir()
    for item in json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8")):
        shutil.copy2(
            FIXTURES / (item["label"] + ".html"),
            OUT / "fixtures" / (item["label"] + ".html"),
        )
    for name in ("robots.txt", "robots_RAW_bytes.txt", "manifest.json"):
        shutil.copy2(FIXTURES / name, OUT / "fixtures" / name)
    (OUT / "scope.json").write_text(
        json.dumps(scope(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8")
    (OUT / "run_loop.ps1").write_text(
        "$ErrorActionPreference = 'Continue'\n"
        "$root = 'D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив'\n"
        "Set-Location $root\n"
        "$outDir = Join-Path $root 'output\\rgada_catalog_full_20260922_v3'\n"
        "for ($i = 1; $i -le 60; $i++) {\n"
        "  & python -B 'output/rgada_catalog_full_handoff_20260922_v3/run_catalog.py'\n"
        "  if ($LASTEXITCODE -ne 3) { break }\n"
        "  Start-Sleep -Seconds 5\n"
        "}\n",
        encoding="utf-8",
    )
    manifest = {
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "continuation": {
            "working_output": "output/rgada_catalog_full_20260922_v3",
            "scope_sha256": sha(OUT / "scope.json"),
            "accepted_prior_module_hashes": [],
            "prior_package": "output/rgada_catalog_full_handoff_20260921_v2",
            "state_migration": "not_applicable_new_query_model_and_output",
        },
        "source": {
            "base_url": "http://rgada.info/",
            "record_level": "archival_inventory",
            "network": "not_run",
        },
        "query_model": scope()["query_model"],
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    check = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('rgada_v3',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(OUT / "run_catalog.py"),
        ],
        text=True,
        capture_output=True,
    )
    if check.returncode:
        raise SystemExit("Frozen verification failed: " + check.stdout + check.stderr)
    validation = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "not_run",
        "local_pytest_exit_code": 0,
        "local_pytest_summary": next(
            (line.strip() for line in reversed(tests.stdout.splitlines()) if "passed" in line),
            "unknown",
        ),
        "frozen_verify": True,
        "manifest_sha256": sha(OUT / "manifest.json"),
        "query_model": scope()["query_model"],
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()