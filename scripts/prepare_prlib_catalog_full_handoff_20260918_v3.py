"""Собрать frozen-пакет v3 с заверенной миграцией состояния ПрБ без сети."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output" / "prlib_catalog_full_handoff_20260918_v2"
OUT = ROOT / "output" / "prlib_catalog_full_handoff_20260918_v3"
WORKING_OUTPUT = ROOT / "output" / "prlib_catalog_full_20260917_v1"
MODULES = ("classify_stop.py", "prlib_access.py", "prlib_card.py", "prlib_run_state.py", "searcher_libraries.py")
HASH_FIELDS = ("parser_sha256", "access_sha256", "detail_sha256")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Cannot apply v3 runner change {label!r}")
    return text.replace(old, new)


def accepted_prior_hashes() -> list[dict[str, str]]:
    triples = []
    for path in sorted((WORKING_OUTPUT / "prlib_query_state").glob("*.json")):
        scope = json.loads(path.read_text(encoding="utf-8"))["scope"]
        triple = {field: scope[field] for field in HASH_FIELDS}
        if any(not isinstance(value, str) or len(value) != 64 for value in triple.values()):
            raise ValueError(f"Invalid state hash in {path.name}")
        triples.append(triple)
    if not triples:
        raise ValueError("No preserved PRLIB query state for migration whitelist")
    unique = []
    for triple in triples:
        if triple not in unique:
            unique.append(triple)
    return unique


def runner_v3(source: str) -> str:
    source = replace_once(
        source,
        '"""Frozen PRLIB metadata collector v2. CLI has no scope overrides. No image fetching."""',
        '"""Frozen PRLIB metadata collector v3. CLI has no scope overrides. No image fetching."""',
        "header",
    )
    source = replace_once(
        source,
        "from prlib_run_state import atomic_json,existing_outputs,identity,iter_query,query_path,completed_query\n"
        "from notion_export import export as export_candidates",
        "from prlib_run_state import atomic_json,existing_outputs,identity,iter_query,query_path,completed_query,configure_migration\n"
        "configure_migration(manifest()['continuation']['accepted_prior_module_hashes'],sha(PACKAGE/'manifest.json'))\n"
        "from notion_export import export as export_candidates",
        "migration configuration",
    )
    source = replace_once(
        source,
        "      'collector_version':'20260918_v2','continuation_from_v1':continuation,",
        "      'collector_version':'20260918_v3','continuation_from_v1':continuation,",
        "collector version",
    )
    source = replace_once(
        source,
        "  except Exception as exc:\n"
        "   log.update(status='stopped',error_type=type(exc).__name__)\n"
        "   log['stop_reason']=log['stop_reason'] or getattr(exc,'reason',None) or cov.get('stop_reason') or 'local_error';rc=2",
        "  except Exception as exc:\n"
        "   log.update(status='stopped',error_type=type(exc).__name__,error_message=str(exc)[:1000])\n"
        "   log['stop_reason']=log['stop_reason'] or getattr(exc,'reason',None) or cov.get('stop_reason') or 'local_error';rc=2",
        "report exception message",
    )
    source = replace_once(
        source,
        "   except Exception as exc:log.update(status='validation_failed',validation_error_type=type(exc).__name__);rc=1",
        "   except Exception as exc:log.update(status='validation_failed',validation_error_type=type(exc).__name__,validation_error_message=str(exc)[:1000]);rc=1",
        "validation exception message",
    )
    return source


def instructions() -> str:
    return """# Полный проход метаданных ПрБ — пакет v3

Продолжи закреплённый каталожный проход из `output/prlib_catalog_full_20260917_v1`.

1. Выполни `python -B output/prlib_catalog_full_handoff_20260918_v3/run_catalog.py` из корня проекта.
2. Повторять ту же команду разрешено только при `exit_code=3` и `stop_reason=request_budget`; между вызовами — минимум 3 секунды. Не запускай два процесса одновременно.
3. При любом другом коде, `real_barrier`, robots, транспорте, `unverified`, несоответствии файлов или незаверенной тройке хешей остановись без повтора и передай человеку `attempts/.../REPORT.json`.
4. При exit 0 проверь `query_scope_complete=true` и `completed_queries=total_queries=294`.

## Заверенная миграция состояния

Этот пакет продолжает тот же output и не меняет область, `scope.json`, данные JSONL/CSV или уже завершённый запрос №1. При несовпадении только трёх хешей модулей state может быть мигрирован лишь если прежняя точная тройка входит в `manifest.json → continuation.accepted_prior_module_hashes`. Все прочие поля scope (`key`, `query`, годы, `detail_mode`, `state_schema`) сравниваются строго. Миграция выполняется через atomic_json и оставляет в state запись `from_hashes`, `to_hashes`, UTC и хеш manifest. Незнакомая тройка — жёсткий `ValueError`, без сети.

Барьеры не обходятся. `real_barrier` возвращается человеку; подтверждённый конец выдачи `reported_end` не является барьером; пустая выдача без подтверждённого конца остаётся `unverified`. Разрешены только прежние HTTPS GET в robots-ограниченной области ПрБ. Изображения, OCR, связанные издания, Notion и canonical-онтология не входят в запуск; все записи candidate, `ready_for_import=false`.
"""


def run_loop() -> str:
    return """# Обёртка полного прохода ПрБ v3: продолжает только request_budget.
$ErrorActionPreference = \"Continue\"
$root = \"D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив\"
Set-Location $root
$outDir = \"$root\\output\\prlib_catalog_full_20260917_v1\"
$maxCalls = 60
for ($i = 1; $i -le $maxCalls; $i++) {
    Write-Output \"=== CALL $i $(Get-Date -Format o) ===\"
    & python -B \"output/prlib_catalog_full_handoff_20260918_v3/run_catalog.py\"
    $code = $LASTEXITCODE
    Write-Output \"=== CALL $i exit_code=$code ===\"
    if ($code -eq 0) { Write-Output \"DONE: exit 0\"; break }
    if ($code -ne 3) { Write-Output \"STOP: exit $code (not budget) — no retry\"; break }
    $lastReport = Get-ChildItem \"$outDir\\attempts\" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1 |
        ForEach-Object { Join-Path $_.FullName \"REPORT.json\" }
    if (-not $lastReport -or -not (Test-Path $lastReport)) { Write-Output \"STOP: exit 3 but no REPORT.json found — no retry\"; break }
    $sr = (Get-Content $lastReport -Raw -Encoding UTF8 | ConvertFrom-Json).stop_reason
    if ($sr -ne \"request_budget\") { Write-Output \"STOP: stop_reason '$sr' != request_budget — no retry\"; break }
    Start-Sleep -Seconds 5
}
Write-Output \"=== LOOP FINISHED $(Get-Date -Format o) ===\"
"""


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"Refusing to overwrite existing package: {OUT}")
    if not SOURCE.is_dir() or not WORKING_OUTPUT.is_dir():
        raise SystemExit("Missing v2 package or preserved v1 working output")
    tests = subprocess.run([sys.executable, "-B", "-m", "pytest"], cwd=ROOT / "tests", text=True, capture_output=True)
    if tests.returncode:
        sys.stdout.write(tests.stdout)
        sys.stderr.write(tests.stderr)
        raise SystemExit("Local tests failed; v3 package was not created")
    accepted = accepted_prior_hashes()
    shutil.copytree(SOURCE, OUT, ignore=shutil.ignore_patterns("manifest.json", "LOCAL_VALIDATION.json", "run_loop_console.log"))
    frozen = OUT / "frozen" / "scripts" / "modules"
    for name in MODULES:
        shutil.copy2(ROOT / "scripts" / "modules" / name, frozen / name)
    (OUT / "run_catalog.py").write_text(runner_v3((SOURCE / "run_catalog.py").read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    (OUT / "run_loop.ps1").write_text(run_loop(), encoding="utf-8", newline="\n")
    (OUT / "INSTRUCTIONS.md").write_text(instructions(), encoding="utf-8", newline="\n")
    source_manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    project_files = {p.relative_to(OUT / "frozen").as_posix(): sha256(p) for p in sorted((OUT / "frozen").rglob("*")) if p.is_file()}
    package_files = {p.relative_to(OUT).as_posix(): sha256(p) for p in sorted(OUT.rglob("*")) if p.is_file() and "frozen" not in p.parts}
    manifest = {
        "project_files": project_files,
        "package_files": package_files,
        "dependencies": source_manifest["dependencies"],
        "continuation": {
            "prior_package": source_manifest["continuation"]["prior_package"],
            "prior_manifest_sha256": source_manifest["continuation"]["prior_manifest_sha256"],
            "working_output": "output/prlib_catalog_full_20260917_v1",
            "scope_sha256": sha256(OUT / "scope.json"),
            "accepted_prior_module_hashes": accepted,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    check = subprocess.run(
        [sys.executable, "-B", "-c", "import importlib.util; p=r'" + str(OUT / "run_catalog.py") + "'; s=importlib.util.spec_from_file_location('v3',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.verify())"],
        text=True,
        capture_output=True,
    )
    if check.returncode or check.stdout.strip() != "True":
        shutil.rmtree(OUT)
        raise SystemExit("Frozen v3 verification failed: " + check.stderr + check.stdout)
    validation = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "not_run",
        "local_pytest_exit_code": tests.returncode,
        "local_pytest_summary": next((line.strip() for line in reversed(tests.stdout.splitlines()) if "passed" in line), "unknown"),
        "frozen_verify": True,
        "manifest_sha256": sha256(OUT / "manifest.json"),
        "accepted_prior_module_hashes": accepted,
        "run_loop_output": "output/prlib_catalog_full_20260917_v1",
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
