"""Build isolated PermKrai maps-rubric v4; preserve all earlier packages."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "output/permkrai_catalog_maps_handoff_20260926_v3"
OUT = ROOT / "output/permkrai_catalog_maps_handoff_20260927_v4"
TEMPLATE = ROOT / "scripts/permkrai_maps_rubric_runner.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(base: Path) -> dict[str, str]:
    return {path.relative_to(base).as_posix(): sha(path) for path in sorted(base.rglob("*")) if path.is_file()}


def checked(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result


def main() -> None:
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    if not V3.is_dir() or not TEMPLATE.is_file():
        raise FileNotFoundError("Verified v3 package or v4 runner template is absent")
    OUT.mkdir()
    shutil.copytree(V3 / "frozen", OUT / "frozen")
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
        "scope_variant": "maps_rubric_node_722_v4",
        "scope_origin": "public rubric node/722, Карты, схемы, планы; structural map-card classifier excludes thematic collections",
        "rubric_node_id": 722,
        "rubric_url": "https://lib.permkrai.ru/node/722",
        "allowed_explicit_routes": ["/robots.txt", "/node/*"],
        "prohibited_routes": ["/search/", "/admin/", "/user/", "/node/add/"],
        "pagination": {"status": "determined_during_live_run", "supported": ["page_parameter", "rendered_scroll", "single_rendered_page"], "unresolved_action": "partial_stop_no_false_completion"},
        "discovery": {"card_grid_required": True, "detail_classifier": "map_card|collection|unknown", "unknown_action": "partial_stop_with_raw_html"},
        "min_crawl_delay": 10,
        "max_get_per_invocation": 60,
        "transport_retry_backoff_seconds": [5, 15],
        "transport": "playwright_channel_chrome_headed_quic",
        "module_sha256": sha(frozen / "scrapers/searcher_permkrai.py"),
        "csv_scalar_columns": 65,
        "ready_for_import": False,
        "scope_version": "20260927_v4_maps_card_parser",
    }
    (OUT / "scope.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "INSTRUCTIONS.md").write_text(
        """# Пермская краевая библиотека: рубрика карт v4

Вызов открывает только `robots.txt`, рубрику `/node/722` и карточки `/node/{id}`
через headed Google Chrome (`channel=chrome`, QUIC). Он никогда не использует
`/search/`, POST, логин, proxy/VPN или профиль пользователя. Между явными GET
соблюдается crawl-delay не ниже 10 с.

Discovery берёт ссылки только из сетки рубрики. Перед парсингом каждый node
классифицируется: карта требует устойчивых detail-меток Drupal и бейдж/действие;
тематическая коллекция исключается с provenance; неизвестная структура даёт
partial `exit 2`. HTML каждой полученной node-страницы сохраняется до парсинга в
`attempt/raw_cards/`. В JSONL остаются полный текст, raw HTML, даты, шифры и
серия. Библиографическое описание — master «Описание»; PDF идёт в поле 63,
просмотрщик «ОТКРЫТЬ» — в поле 19 как наличие скана. CSV содержит 65 полей,
`ready_for_import=false`; Notion не вызывается.

```powershell
python -B output/permkrai_catalog_maps_handoff_20260927_v4/run_catalog.py --maps-rubric
```
""", encoding="utf-8")
    (OUT / "run_loop.ps1").write_text(
        """$ErrorActionPreference = 'Continue'
$root = 'D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив'
Set-Location $root
for ($i = 1; $i -le 100; $i++) {
  & python -B 'output/permkrai_catalog_maps_handoff_20260927_v4/run_catalog.py' --maps-rubric
  if ($LASTEXITCODE -ne 3) { break }
  Start-Sleep -Seconds 15
}
""", encoding="utf-8")
    manifest = {
        "package": "permkrai_catalog_maps_handoff_20260927_v4", "source": "permkrai",
        "network": "not_run", "ready_for_import": False, "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "continuation": {"working_output": "output/permkrai_catalog_maps_20260927_v4",
            "exit_3_only": "same command resumes after request_budget",
            "exit_2": "partial stop; inspect coverage, requests and raw_cards before any next decision"},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runner = OUT / "run_catalog.py"
    checked([sys.executable, "-B", "-c", "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('permkrai_v4',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(runner)], ROOT)
    validation = checked([sys.executable, "-B", str(runner), "--offline-self-test"], ROOT)
    data = json.loads(validation.stdout.splitlines()[-1])
    if data["rows"] != 2 or data["columns"] != 65 or data["search_called"]:
        raise RuntimeError("v4 offline validation failed: " + validation.stdout)
    result = {"network": "not_run", "frozen_verify": True, "offline_self_test": data,
              "manifest_sha256": sha(OUT / "manifest.json")}
    (OUT / "LOCAL_VALIDATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
