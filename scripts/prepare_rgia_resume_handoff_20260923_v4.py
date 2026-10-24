"""Build the immutable RGIA 20/74 continuation package without network."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/rgia_catalog_resume_handoff_20260923_v4"
RUNNER = ROOT / "scripts/rgia_resume_runner.py"
PRIOR_OUTPUT = ROOT / "output/rgia_catalog_full_20260923_v1"
PRIOR_PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260923_v1"
MODULES = (
    "classify_stop.py", "durable_state.py", "notion_export.py", "rgia_notion.py",
    "library_dates.py", "cartographic_enrichment.py", "administrative_level.py",
    "object_types.json", "notion_schema.json", "scrapers/searcher_rgia.py",
)
FIXTURES = (
    ROOT / "output/rgia_fixtures_2026-09-22/live_WORKING_karta_kaluzhsk.html",
    ROOT / "output/rgia_fixtures_2026-09-22/robots_RAW_bytes.txt",
    ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json",
)

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def hashes(base):
    return {p.relative_to(base).as_posix(): sha(p) for p in sorted(base.rglob("*")) if p.is_file()}

def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    scope = json.loads((PRIOR_OUTPUT / "rgia_query_state.json").read_text(encoding="utf-8"))["scope"]
    if not (PRIOR_OUTPUT / "records_full.jsonl").exists():
        raise FileNotFoundError("prior candidate JSONL missing")
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
    (OUT / "scope.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "INSTRUCTIONS.md").write_text("""# РГИА: продолжение узкого обхода 20/74 с nPage

Команда (один ручной запуск):

    python -B output/rgia_catalog_resume_handoff_20260923_v4/run_catalog.py

Пакет принимает только точный сохранённый scope `карта калужск` из
`output/rgia_catalog_full_20260923_v1`. Он сохраняет уже полученные 20
candidate-строк и их completed_ids; detail GET выполняются только для остальных
ID. `run_scope.json` и `rgia_query_state.json` получают auditable migration с
хешем нового manifest. Изменение территории, запроса, дат или state scope
останавливает запуск до сети.

РГИА jstree держит page=1, а список узла «Дела» листается параметром nPage=1..N; N берётся из счётчика узла. Каждая следующая страница обязана добавить новые numeric ID, иначе состояние получает partial/review, а не reported_end. Detail без однозначной пары
заголовок + `Ф. N Оп. N Д. N` не является candidate: его URL, SHA-256 и
причина помещаются в `for_review`; обход продолжится. Итог будет
`query_scope_review`, если такие узлы встретились.

Только HTTPS GET к fgurgia.ru, robots.txt и crawl-delay не менее 3 секунд.
Запрещены POST/формы, авторизация, CAPTCHA-обход, VPN/proxy, headless, Notion
API и canonical ontology. При любом nonzero exit не повторять автоматически:
вернуть человеку REPORT.json, requests.json и RESUME_MIGRATION.json (если есть).
""", encoding="utf-8")
    manifest = {
        "package": "rgia_catalog_resume_handoff_20260923_v4",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"base_url": "https://fgurgia.ru", "network": "not_run"},
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "fixtures": {x.name: sha(fixtures / x.name) for x in FIXTURES},
        "continuation": {
            "working_output": "output/rgia_catalog_full_20260923_v1",
            "prior_package": "output/rgia_catalog_full_handoff_20260923_v1",
            "prior_package_manifest_sha256": sha(PRIOR_PACKAGE / "manifest.json"),
            "accepted_prior_scope_sha256": hashlib.sha256(json.dumps(scope, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "preserve_completed_candidate_records": 20,
            "state_migration": "exact_scope_only",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    check = subprocess.run([sys.executable, "-B", "-c", "import importlib.util;p=importlib.util.spec_from_file_location('x',r'{}');m=importlib.util.module_from_spec(p);p.loader.exec_module(m);assert m.verify()".format(OUT / "run_catalog.py")], cwd=ROOT, text=True, capture_output=True)
    if check.returncode:
        raise RuntimeError(check.stdout + check.stderr)
    value = {"network": "not_run", "frozen_verify": True, "manifest_sha256": sha(OUT / "manifest.json")}
    (OUT / "LOCAL_VALIDATION.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))
if __name__ == "__main__":
    main()
