"""Собрать отдельный frozen-пакет v2 для продолжения каталожного прохода ПрБ.

Пакет не выполняет сеть: он сначала запускает локальные тесты, затем копирует
v1 как неизменяемую основу и заменяет только проверенные модули классификации.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output" / "prlib_catalog_full_handoff_20260917_v1"
OUT = ROOT / "output" / "prlib_catalog_full_handoff_20260918_v2"
MODULES = ("prlib_access.py", "searcher_libraries.py", "classify_stop.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Cannot apply v2 runner change {label!r}")
    return text.replace(old, new)


def runner_v2(source: str) -> str:
    source = replace_once(
        source,
        '"""Frozen PRLIB metadata collector. CLI has no scope overrides. No image fetching."""',
        '"""Frozen PRLIB metadata collector v2. CLI has no scope overrides. No image fetching."""',
        "header",
    )
    source = replace_once(
        source,
        "def utc():return datetime.now(timezone.utc).isoformat()\n"
        "def verify():\n"
        " m=json.loads((PACKAGE/'manifest.json').read_text(encoding='utf-8'))",
        "def utc():return datetime.now(timezone.utc).isoformat()\n"
        "def manifest():return json.loads((PACKAGE/'manifest.json').read_text(encoding='utf-8'))\n"
        "def verify():\n"
        " m=manifest()",
        "manifest helper",
    )
    source = replace_once(
        source,
        "for name in ('prlib_access','prlib_card','searcher_libraries','prlib_run_state','registry','notion_export'):",
        "for name in ('classify_stop','prlib_access','prlib_card','searcher_libraries','prlib_run_state','registry','notion_export'):",
        "frozen module allowlist",
    )
    source = replace_once(
        source,
        " seal={'scope':scope,'manifest_sha256':sha(PACKAGE/'manifest.json'),'network_mode':mode}\n"
        " sealfile=out/'run_scope.json'\n"
        " if sealfile.exists():\n"
        "  if json.loads(sealfile.read_text(encoding='utf-8'))!=seal:raise ValueError('Run scope mismatch')\n"
        " else:\n"
        "  if any((out/x).exists() for x in ('records_full.jsonl','prlib_query_state')):raise ValueError('Unsealed prior outputs')\n"
        "  atomic_json(sealfile,seal)",
        " seal={'scope':scope,'manifest_sha256':sha(PACKAGE/'manifest.json'),'network_mode':mode}\n"
        " sealfile=out/'run_scope.json'\n"
        " continuation=False\n"
        " if sealfile.exists():\n"
        "  prior=json.loads(sealfile.read_text(encoding='utf-8'))\n"
        "  continuation_seal={'scope':scope,'manifest_sha256':manifest()['continuation']['prior_manifest_sha256'],'network_mode':'live'}\n"
        "  continuation=(mode=='live' and prior==continuation_seal)\n"
        "  if prior!=seal and not continuation:raise ValueError('Run scope mismatch')\n"
        " else:\n"
        "  if any((out/x).exists() for x in ('records_full.jsonl','prlib_query_state')):raise ValueError('Unsealed prior outputs')\n"
        "  atomic_json(sealfile,seal)",
        "continuation seal",
    )
    source = replace_once(
        source,
        " log={'started_at':utc(),'network_mode':mode,'hashes_before':True,'ready_for_import':False,\n"
        "      'metadata_only':True,'images_ocr':'deferred','related_editions':'pending_review',",
        " log={'started_at':utc(),'network_mode':mode,'hashes_before':True,'ready_for_import':False,\n"
        "      'collector_version':'20260918_v2','continuation_from_v1':continuation,\n"
        "      'metadata_only':True,'images_ocr':'deferred','related_editions':'pending_review',",
        "report provenance",
    )
    source = replace_once(
        source,
        "  response.access_report['local_file']=str(path.relative_to(out))\n"
        "  return response",
        "  response.access_report['local_file']=str(path.relative_to(out))\n"
        "  verdict=response.access_report.get('classification',{})\n"
        "  if verdict:\n"
        "   durable_line(attempt/'requests.jsonl',{'utc':utc(),'url':response.url,'event':'classification','verdict':verdict.get('verdict'),'reason':verdict.get('reason')})\n"
        "  return response",
        "classification journal",
    )
    source = replace_once(
        source,
        "     coverage.append({'key':key,'status':state.get('status','not_started'),'stop_reason':state.get('stop_reason',''),'resume_page':state.get('resume',{}).get('page')})",
        "     verdicts=state.get('classifier_verdicts',[])\n"
        "     last_verdict=verdicts[-1] if verdicts else {}\n"
        "     coverage.append({'key':key,'status':state.get('status','not_started'),'stop_reason':state.get('stop_reason',''),'resume_page':state.get('resume',{}).get('page'),'classifier_verdict':last_verdict.get('verdict',''),'classifier_reason':last_verdict.get('reason','')})",
        "coverage classifier fields",
    )
    return source


def instructions() -> str:
    return """# Полный проход метаданных ПрБ — пакет v2

Продолжи закреплённый каталожный проход ПрБ из `output/prlib_catalog_full_20260917_v1`.

1. Работай в `D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив`.
2. Выполни `python -B output/prlib_catalog_full_handoff_20260918_v2/run_catalog.py`.
3. При exit_code=3 и stop_reason=request_budget продолжай той же командой: максимум 500 GET за вызов, положение сохраняется. Не запускай два процесса одновременно. Между вызовами выдерживай минимум 3 секунды. Каждый вызов создаёт новый каталог attempts. Продолжай до завершения области или другой причины остановки.
4. При exit_code=0 проверь query_scope_complete=true и completed_queries=total_queries=294. При любом другом коде, CAPTCHA, запрете robots, ошибке транспорта, отсутствии подтверждённого окончания или несовпадении файлов остановись без повтора и передай частичный результат. Не удаляй оставшийся после аварии collector.lock автоматически.
5. Верни путь attempts/.../REPORT.json, код возврата, число запросов/записей/уникальных URL, completed_queries/294, stop_reason, hashes_before/after, roundtrip и сводку coverage.json, включая classifier_verdict/classifier_reason.

## Граница доступа

Барьеры не обходятся. `real_barrier` останавливает прогон и возвращается человеку. Конец выдачи распознаётся `classify_stop` и барьером не является: пустой ответ с подтверждённым маркером получает `reported_end` и закрывает запрос как `pager_reported_end`; пустой ответ без подтверждённого конца остаётся `unverified` и останавливает сбор. Форма входа и input[type=password] — только информационный сигнал, не причина остановки.

Выход остаётся `output/prlib_catalog_full_20260917_v1`: это накопительное продолжение существующего состояния. Завершённый запрос №1 не перезапускается. `scope.json`, область 49 территориальных формулировок × 6 слов и существующий `run_scope.json` не изменяются; v2 допускает только прежнюю печать v1 после точной проверки scope. Новый v2-пакет самодостаточно frozen и не меняет v1.

Разрешены только HTTPS GET robots.txt на prlib.ru/www.prlib.ru, поисковые страницы закреплённых запросов и /item/<id>, найденные текущим парсером. Сохраняются TLS, robots, задержка не менее 3 секунд и отсутствие повторов транспортных ошибок. Изображения, OCR, просмотрщики, связанные издания, Notion и canonical-онтология не входят в запуск. Все экспорты candidate, ready_for_import=false.
"""


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"Refusing to overwrite existing package: {OUT}")
    if not SOURCE.is_dir():
        raise SystemExit(f"Missing v1 package: {SOURCE}")
    tests = subprocess.run([sys.executable, "-B", "-m", "pytest"], cwd=ROOT / "tests", text=True, capture_output=True)
    if tests.returncode:
        sys.stdout.write(tests.stdout)
        sys.stderr.write(tests.stderr)
        raise SystemExit("Local tests failed; v2 package was not created")
    shutil.copytree(SOURCE, OUT)
    frozen = OUT / "frozen" / "scripts" / "modules"
    for name in MODULES:
        shutil.copy2(ROOT / "scripts" / "modules" / name, frozen / name)
    (OUT / "run_catalog.py").write_text(runner_v2((SOURCE / "run_catalog.py").read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    (OUT / "run_loop.ps1").write_text((SOURCE / "run_loop.ps1").read_text(encoding="utf-8").replace("20260917_v1", "20260918_v2"), encoding="utf-8", newline="\n")
    (OUT / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8", newline="\n")
    prior_manifest = sha256(SOURCE / "manifest.json")
    project_files = {p.relative_to(OUT / "frozen").as_posix(): sha256(p) for p in sorted((OUT / "frozen").rglob("*")) if p.is_file()}
    package_files = {p.relative_to(OUT).as_posix(): sha256(p) for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "manifest.json" and "frozen" not in p.parts}
    source_manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "project_files": project_files,
        "package_files": package_files,
        "dependencies": source_manifest["dependencies"],
        "continuation": {
            "prior_package": "prlib_catalog_full_handoff_20260917_v1",
            "prior_manifest_sha256": prior_manifest,
            "working_output": "output/prlib_catalog_full_20260917_v1",
            "scope_sha256": sha256(OUT / "scope.json"),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    check = subprocess.run(
        [sys.executable, "-B", "-c", "import importlib.util; p=r'" + str(OUT / "run_catalog.py") + "'; s=importlib.util.spec_from_file_location('v2',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.verify())"],
        text=True,
        capture_output=True,
    )
    if check.returncode or check.stdout.strip() != "True":
        shutil.rmtree(OUT)
        raise SystemExit("Frozen v2 verification failed: " + check.stderr + check.stdout)
    validation = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "not_run",
        "local_pytest_exit_code": tests.returncode,
        "local_pytest_summary": next((line.strip() for line in reversed(tests.stdout.splitlines()) if "passed" in line), "unknown"),
        "frozen_verify": True,
        "manifest_sha256": sha256(OUT / "manifest.json"),
        "prior_manifest_sha256": prior_manifest,
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
