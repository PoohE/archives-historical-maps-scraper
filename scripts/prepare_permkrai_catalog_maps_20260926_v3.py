"""Build the isolated PermKrai maps-rubric v3 frozen package; v1/v2 stay unchanged."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "output/permkrai_catalog_full_handoff_20260926_v2"
OUT = ROOT / "output/permkrai_catalog_maps_handoff_20260926_v3"
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
    if not V2.is_dir() or not TEMPLATE.is_file():
        raise FileNotFoundError("Verified v2 package or v3 runner template is absent")
    OUT.mkdir()
    shutil.copytree(V2 / "frozen", OUT / "frozen")
    frozen_modules = OUT / "frozen/scripts/modules"
    current = ROOT / "scripts/modules"
    for relative in (
        "classify_stop.py", "notion_export.py", "notion_schema.json", "permkrai_chrome_transport.py",
        "permkrai_notion.py", "scrapers/searcher_permkrai.py",
    ):
        target = frozen_modules / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current / relative, target)
    shutil.copy2(TEMPLATE, OUT / "run_catalog.py")
    scope = {
        "source": "permkrai",
        "scope_variant": "maps_rubric_node_722",
        "scope_origin": "public rubric node/722, Карты, схемы, планы; not search and not the 294-query scope",
        "rubric_node_id": 722,
        "rubric_url": "https://lib.permkrai.ru/node/722",
        "allowed_explicit_routes": ["/robots.txt", "/node/*"],
        "prohibited_routes": ["/search/", "/admin/", "/user/", "/node/add/"],
        "year_from": None,
        "year_to": None,
        "pagination": {
            "status": "determined_during_live_run",
            "supported": ["page_parameter", "rendered_scroll", "single_rendered_page"],
            "unresolved_action": "partial_stop_no_false_completion",
        },
        "min_crawl_delay": 10,
        "max_get_per_invocation": 60,
        "transport_retry_backoff_seconds": [5, 15],
        "transport": "playwright_channel_chrome_headed_quic",
        "module_sha256": sha(frozen_modules / "scrapers/searcher_permkrai.py"),
        "csv_scalar_columns": 65,
        "ready_for_import": False,
        "scope_version": "20260926_v3_maps_rubric",
    }
    (OUT / "scope.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "INSTRUCTIONS.md").write_text(
        """# Пермская краевая библиотека: карты, схемы, планы v3

Запуск использует headed Google Chrome через Playwright (`channel=chrome`, QUIC)
и чистый временный профиль. Явные навигации допускаются только к `robots.txt` и
`/node/*` на `lib.permkrai.ru`; `/search/` никогда не вызывается. Источник — вся
публичная рубрика `/node/722` «Карты, схемы, планы», а не прежний reduced-first
поиск и не полный 294-query scope. Между навигациями соблюдается crawl-delay не
ниже 10 с. Пагинация определяется и фиксируется во время первого запуска:
поддержаны `?page=N` и отрисованный scroll; нераспознанный конец даёт partial
stop, а не ложную полноту.

Карточки сохраняются как candidates: полный текст и HTML страховка, сырьё
шифров/дат/серии остаются в JSONL; PDF/file URL маппится в поле 63, прямая
image URL — в поле 19, если такая ссылка прямо присутствует в карточке. CSV
содержит 65 полей. `ready_for_import=false`; Notion не вызывается.

```powershell
python -B output/permkrai_catalog_maps_handoff_20260926_v3/run_catalog.py --maps-rubric
```
""",
        encoding="utf-8",
    )
    (OUT / "run_loop.ps1").write_text(
        """$ErrorActionPreference = 'Continue'
$root = 'D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив'
Set-Location $root
for ($i = 1; $i -le 100; $i++) {
  & python -B 'output/permkrai_catalog_maps_handoff_20260926_v3/run_catalog.py' --maps-rubric
  if ($LASTEXITCODE -ne 3) { break }
  Start-Sleep -Seconds 15
}
""",
        encoding="utf-8",
    )
    manifest = {
        "package": "permkrai_catalog_maps_handoff_20260926_v3",
        "source": "permkrai",
        "network": "not_run",
        "ready_for_import": False,
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "continuation": {
            "working_output": "output/permkrai_catalog_maps_20260926_v3",
            "exit_3_only": "same command resumes after request_budget",
            "exit_2": "partial stop; inspect coverage and requests before any next decision",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runner = OUT / "run_catalog.py"
    checked([sys.executable, "-B", "-c", "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('permkrai_v3',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(runner)], ROOT)
    validation = checked([sys.executable, "-B", str(runner), "--offline-self-test"], ROOT)
    data = json.loads(validation.stdout.splitlines()[-1])
    if data["rows"] != 2 or data["columns"] != 65 or data["search_called"]:
        raise RuntimeError("v3 offline validation failed: " + validation.stdout)
    result = {"network": "not_run", "frozen_verify": True, "offline_self_test": data,
              "manifest_sha256": sha(OUT / "manifest.json")}
    (OUT / "LOCAL_VALIDATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
