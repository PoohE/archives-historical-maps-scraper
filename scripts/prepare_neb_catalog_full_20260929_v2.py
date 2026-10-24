"""Freeze the NEB headed-Chrome scraper without performing a network run."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/neb_catalog_full_handoff_20260929_v2"
RUNNER = ROOT / "scripts/neb_fullsweep_runner_v1.py"
MODULES = (
    "notion_export.py", "notion_schema.json", "neb_notion.py", "library_dates.py",
    "cartographic_enrichment.py", "administrative_level.py", "scrapers/neb_card_dom.py",
)
FIXTURES = (
    ROOT / "output/neb_recon_20260928_v1/raw_html/card_book_rendered.html",
    ROOT / "output/neb_recon_20260928_v1/raw_html/card_map_rendered.html",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite {OUT}")
    source_tests = run([sys.executable, "-B", "-m", "pytest", "test_neb_card_dom.py", "test_neb_export.py", "-q"], ROOT / "tests")
    run([sys.executable, "-B", "-m", "py_compile", str(RUNNER)], ROOT)
    frozen = OUT / "frozen/scripts/modules"
    for rel in MODULES:
        target = frozen / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts/modules" / rel, target)
    shutil.copy2(RUNNER, OUT / "run_catalog.py")
    fixture_dir = OUT / "fixtures"
    fixture_dir.mkdir()
    for source in FIXTURES:
        shutil.copy2(source, fixture_dir / source.name)
    scope = {
        "source": "neb", "scope_version": "20260929_gubernias_24_v1",
        "territories": ["Калужская губерния", "Пермская губерния", "Смоленская губерния", "Ярославская губерния"],
        "keywords": ["карта", "план", "атлас", "съёмка", "чертёж", "топографическая"],
        "queries": 24, "transport": "Playwright headed channel=chrome clean context",
        "robots_required": True, "min_crawl_delay_seconds": 3, "ready_for_import": False,
    }
    (OUT / "scope.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "INSTRUCTIONS.md").write_text("""# НЭБ: full browser scraper v1

Запускать только из project root и только headed Chrome:

    bash output/neb_catalog_full_handoff_20260929_v2/run_loop.sh

Каждый запуск выполняет один запрос из 24 и создаёт/продолжает durable state
в `output/neb_catalog_full_20260929_v1_gubernias`. Сначала браузером читает и
сохраняет `robots.txt`; разрешены только search и catalog-card URL. Скролл
выдачи выполняется до двух одинаковых наборов ссылок; `page`, `pagen`, API,
viewer и PDF не запрашиваются. Если счётчик результатов отсутствует либо
загружено меньше счётчика, запрос получает `partial`, exit 2 и не называется
полным. 403/401/429 на search/robots останавливает запуск; отказ отдельной
карточки фиксируется `object_reviews` и не блокирует остальные карточки.

Все карточки и robots сохраняются как rendered HTML. `records_full.jsonl` и
65-польный candidate-export остаются review-only; Notion API не вызывается,
`ready_for_import=false`.
""", encoding="utf-8")
    (OUT / "run_loop.sh").write_text("""#!/usr/bin/env bash
set -u
for i in $(seq 1 24); do
  python -B output/neb_catalog_full_handoff_20260929_v2/run_catalog.py --gubernias-only --output output/neb_catalog_full_20260929_v2_gubernias
  code=$?
  [ \"$code\" -eq 3 ] || exit \"$code\"
  sleep 5
done
exit 3
""", encoding="utf-8")
    manifest = {
        "package": OUT.name, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"base_url": "https://rusneb.ru", "network": "not_run"},
        "scope": scope, "project_files": {str(p.relative_to(OUT)): sha(p) for p in sorted((OUT / "frozen").rglob("*")) if p.is_file()},
        "fixtures": {source.name: sha(fixture_dir / source.name) for source in FIXTURES},
        "continuation": {"working_output": "output/neb_catalog_full_20260929_v1_gubernias", "state": "neb_query_state", "one_query_per_invocation": True},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frozen_test = run([sys.executable, "-B", "-m", "pytest", "test_neb_fullsweep_v2.py", "-q"], ROOT / "tests")
    validation = {"network": "not_run", "source_tests": source_tests.stdout.strip(), "frozen_tests": frozen_test.stdout.strip(), "manifest_sha256": sha(OUT / "manifest.json")}
    (OUT / "LOCAL_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
