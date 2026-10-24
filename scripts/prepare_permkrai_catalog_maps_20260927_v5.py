"""Build an isolated PermKrai maps-rubric v5 package from real DOM selectors."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "output/permkrai_catalog_maps_handoff_20260927_v4"
OUT = ROOT / "output/permkrai_catalog_maps_handoff_20260927_v5"
TEMPLATE = ROOT / "scripts/permkrai_maps_rubric_runner.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(base: Path) -> dict[str, str]:
    return {
        path.relative_to(base).as_posix(): sha(path)
        for path in sorted(base.rglob("*")) if path.is_file()
    }


def checked(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result


def main() -> None:
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    if not V4.is_dir() or not TEMPLATE.is_file():
        raise FileNotFoundError("Verified v4 package or v5 runner template is absent")
    checked(
        [sys.executable, "-B", "-m", "pytest", "test_permkrai_v4_card_parser.py", "-q"],
        ROOT / "tests",
    )
    OUT.mkdir()
    shutil.copytree(V4 / "frozen", OUT / "frozen")
    frozen = OUT / "frozen/scripts/modules"
    current = ROOT / "scripts/modules"
    for relative in (
        "cartographic_enrichment.py", "classify_stop.py", "notion_export.py", "notion_schema.json",
        "permkrai_chrome_transport.py", "permkrai_notion.py", "scrapers/searcher_permkrai.py",
    ):
        target = frozen / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current / relative, target)
    shutil.copy2(TEMPLATE, OUT / "run_catalog.py")
    scope = {
        "source": "permkrai",
        "scope_variant": "maps_rubric_node_722_v5",
        "scope_origin": "public rubric node/722; all node links classified by rendered Drupal PDF-node markers",
        "rubric_node_id": 722,
        "rubric_url": "https://lib.permkrai.ru/node/722",
        "allowed_explicit_routes": ["/robots.txt", "/node/*"],
        "prohibited_routes": ["/search/", "/admin/", "/user/", "/node/add/"],
        "pagination": {
            "status": "determined_during_live_run",
            "supported": ["page_parameter", "rendered_scroll", "single_rendered_page"],
            "unresolved_action": "partial_stop_no_false_completion",
        },
        "discovery": {
            "card_grid_required": False,
            "detail_classifier": "body.node-type-pdf|article.node-pdf",
            "unknown_action": "exclude_with_rendered_html",
            "failure_html_path": "attempt/raw_html",
        },
        "min_crawl_delay": 10,
        "max_get_per_invocation": 60,
        "transport_retry_backoff_seconds": [5, 15],
        "transport": "playwright_channel_chrome_headed_quic",
        "module_sha256": sha(frozen / "scrapers/searcher_permkrai.py"),
        "csv_scalar_columns": 65,
        "ready_for_import": False,
        "scope_version": "20260927_v5_real_dom_selectors",
    }
    (OUT / "scope.json").write_text(
        json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "INSTRUCTIONS.md").write_text(
        """# Пермская краевая библиотека: рубрика карт v5

Пакет обращается только к `robots.txt`, рубрике `/node/722` и карточкам
`/node/{id}` через headed Google Chrome (`channel=chrome`, QUIC); `/search/`
никогда не используется. Между GET выдерживается crawl-delay не менее 10 с.

Discovery сохраняет все same-host `/node/{id}` из отрендеренной рубрики, после
чего классифицирует каждую страницу строго по Drupal: карта — только
`body.node-type-pdf` или `article.node-pdf`. Коллекции и прочие non-PDF nodes
исключаются с provenance, а не становятся кандидатами. Карточка извлекает
заголовок и строки `article .subj-library-table`: «Дата публикации», полное
«Библиографическое описание» в «Описание», «Фондодержатель». PDF идёт в поле
63, «ОТКРЫТЬ» — в поле 19; масштаб из библиографии сохраняется и нормализуется.

До классификации и парсинга рендеренный DOM рубрики и каждой карточки пишется
в `attempt/raw_html/`. Поэтому сбой селектора сохраняет фактический HTML и
даёт partial, а не фиктивную полноту. CSV содержит 65 полей; все записи
candidate, `ready_for_import=false`; Notion вызывается только отдельным мостом.

```powershell
python -B output/permkrai_catalog_maps_handoff_20260927_v5/run_catalog.py --maps-rubric
```
""",
        encoding="utf-8",
    )
    (OUT / "run_loop.ps1").write_text(
        """$ErrorActionPreference = 'Continue'
$root = 'D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив'
Set-Location $root
for ($i = 1; $i -le 100; $i++) {
  & python -B 'output/permkrai_catalog_maps_handoff_20260927_v5/run_catalog.py' --maps-rubric
  if ($LASTEXITCODE -ne 3) { break }
  Start-Sleep -Seconds 15
}
""",
        encoding="utf-8",
    )
    manifest = {
        "package": "permkrai_catalog_maps_handoff_20260927_v5",
        "source": "permkrai",
        "network": "not_run",
        "ready_for_import": False,
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "continuation": {
            "working_output": "output/permkrai_catalog_maps_20260927_v5",
            "prior_package": "output/permkrai_catalog_maps_handoff_20260927_v4",
            "exit_3_only": "same command resumes after request_budget",
            "exit_2": "partial stop; inspect coverage, requests and raw_html before any next decision",
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    runner = OUT / "run_catalog.py"
    checked(
        [sys.executable, "-B", "-c", "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('permkrai_v5', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(runner)],
        ROOT,
    )
    validation = checked([sys.executable, "-B", str(runner), "--offline-self-test"], ROOT)
    data = json.loads(validation.stdout.splitlines()[-1])
    if data["rows"] != 2 or data["columns"] != 65 or data["search_called"]:
        raise RuntimeError("v5 offline validation failed: " + validation.stdout)
    regression = checked(
        [sys.executable, "-B", "-m", "pytest", "test_permkrai_maps_rubric_v5.py", "-q"],
        ROOT / "tests",
    )
    result = {
        "network": "not_run", "frozen_verify": True, "offline_self_test": data,
        "frozen_regression": regression.stdout.strip(), "manifest_sha256": sha(OUT / "manifest.json"),
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
