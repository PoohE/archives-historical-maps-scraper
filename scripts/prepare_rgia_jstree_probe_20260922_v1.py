"""Build the frozen, bounded five-GET RGIA jstree probe package."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "output"
PACKAGE = OUTPUT / "rgia_jstree_probe_handoff_20260922_v1"
SOURCE_RUNNER = Path(__file__).with_name("rgia_jstree_probe_runner.py")
SOURCE_SCRAPER = PROJECT / "scripts/modules/scrapers/searcher_rgia.py"
FIXTURES = OUTPUT / "rgia_fixtures_2026-09-22"
TESTS = PROJECT / "tests"
FIXTURE_NAMES = (
    "live_WORKING_karta_kaluzhsk.html",
    "AJAX_pages_SESSION.html",
    "AJAX_pages_113000_p1.html",
    "robots_RAW_bytes.txt",
    "manifest.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative_hashes(base: Path) -> dict[str, str]:
    return {
        path.relative_to(base).as_posix(): digest(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def local_tests() -> dict:
    command = [sys.executable, "-B", "-m", "pytest", "test_rgia_saved.py", "test_rgia_ajax_tree.py", "-q"]
    completed = subprocess.run(command, cwd=TESTS, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError("RGIA source regressions failed:\n" + completed.stdout + "\n" + completed.stderr)
    return {
        "command": command,
        "cwd": str(TESTS),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def instructions() -> str:
    return """# РГИА: ограниченный jstree-probe

Пакет проверяет публичный маршрут списка дел РГИА, но не является полным
сбором и не готовит импорт в Notion или онтологию.

## Граница запуска

Команда: python -B output/rgia_jstree_probe_handoff_20260922_v1/run_probe.py

Разрешены ровно пять последовательных публичных GET к fgurgia.ru с интервалом
3 секунды: robots.txt, один /search с карта калужск, корневой и дочерний
/ajax/tree/{search_index}, затем ровно одна /ajax/obj/{object_id}/{search_index}.
До первого GET проверяются хеши frozen-файлов; после каждого ответа фиксируются
URL, статус, размер и SHA-256. Cookies и тело карточки в request log не сохраняются.

## Условия остановки

Запуск немедленно останавливается при запрете robots, не-200, redirect, выходе
за allowlist, отсутствии search_index/узла Дела/дела или исчерпании бюджета.
Не отправлять формы или POST, не входить в аккаунт, не обходить CAPTCHA/robots/
авторизацию, не применять VPN, прокси или headless-браузер. Не расширять лимит,
не запускать карточки серийно, не записывать в Notion или canonical ontology.

Результат помещается в новый output/rgia_jstree_probe_20260922_v1/ и содержит
одну candidate-запись только при полном прохождении пяти GET.
"""


def build() -> int:
    if PACKAGE.exists():
        raise FileExistsError("Refusing to overwrite existing package: " + str(PACKAGE))
    test_result = local_tests()

    frozen_scraper = PACKAGE / "frozen/scripts/modules/scrapers"
    frozen_scraper.mkdir(parents=True)
    shutil.copy2(SOURCE_SCRAPER, frozen_scraper / "searcher_rgia.py")
    shutil.copy2(SOURCE_RUNNER, PACKAGE / "run_probe.py")

    fixture_target = PACKAGE / "fixtures"
    fixture_target.mkdir()
    for name in FIXTURE_NAMES:
        source = FIXTURES / name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, fixture_target / name)

    (PACKAGE / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8")
    manifest = {
        "package": "rgia_jstree_probe_handoff_20260922_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "rgia",
        "network": "not_run",
        "purpose": "bounded public jstree route probe",
        "scope": {
            "query": "карта калужск",
            "max_get": 5,
            "first_tree_page": 1,
            "max_detail_records": 1,
            "forms_or_post": False,
            "authentication": False,
            "captcha_bypass": False,
            "vpn_or_proxy": False,
            "notion_or_canonical_ontology": False,
        },
        "continuation": {
            "working_output": "output/rgia_jstree_probe_20260922_v1",
            "prior_rgia_handoff": "output/rgia_handoff_20260914_v1",
            "state_migration": "not_applicable_new_bounded_probe",
        },
        "fixtures": {name: digest(fixture_target / name) for name in FIXTURE_NAMES},
        "project_files": relative_hashes(PACKAGE / "frozen"),
        "package_files": relative_hashes(PACKAGE),
        "validation": {"source_regressions": "7 passed", "frozen_verify": True},
    }
    write_json(PACKAGE / "manifest.json", manifest)

    check = subprocess.run(
        [
            sys.executable, "-B", "-c",
            "import importlib.util; p=importlib.util.spec_from_file_location('p', r'{}'); m=importlib.util.module_from_spec(p); p.loader.exec_module(m); assert m.verify()".format(PACKAGE / "run_probe.py"),
        ],
        cwd=PROJECT, text=True, capture_output=True, check=False,
    )
    if check.returncode:
        raise RuntimeError("Frozen verify failed:\n" + check.stdout + "\n" + check.stderr)

    write_json(
        PACKAGE / "LOCAL_VALIDATION.json",
        {
            "network": "not_run",
            "source_tests": test_result,
            "frozen_verify": True,
            "manifest_sha256": digest(PACKAGE / "manifest.json"),
        },
    )
    print(PACKAGE)
    print("manifest_sha256=" + digest(PACKAGE / "manifest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(build())