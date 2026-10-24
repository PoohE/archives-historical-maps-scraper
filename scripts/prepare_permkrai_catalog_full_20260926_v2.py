"""Build a new headed-Chrome PermKrai frozen package; preserve v1 unchanged."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "output/permkrai_catalog_full_handoff_20260926_v1"
OUT = ROOT / "output/permkrai_catalog_full_handoff_20260926_v2"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(base: Path) -> dict[str, str]:
    return {
        path.relative_to(base).as_posix(): sha(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def checked(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return result


def main() -> None:
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    if not V1.is_dir():
        raise FileNotFoundError("Required verified v1 package is absent: " + str(V1))
    OUT.mkdir()
    shutil.copytree(V1 / "frozen", OUT / "frozen")
    shutil.copy2(V1 / "run_catalog.py", OUT / "run_catalog.py")
    runner = OUT / "run_catalog.py"
    source = runner.read_text(encoding="utf-8")
    source = source.replace(
        "import searcher_permkrai as permkrai  # noqa: E402\n",
        "import searcher_permkrai as permkrai  # noqa: E402\nfrom permkrai_chrome_transport import ChromeTransport  # noqa: E402\n",
        1,
    )
    source = source.replace(
        'COLS = tuple(k for k in asdict(permkrai.PermRecord()) if k not in {"extra_json", "card_text"})',
        'COLS = tuple(k for k in asdict(permkrai.PermRecord()) if k not in {"extra_json", "card_text", "card_html", "identifiers_raw", "dates_raw", "series_raw"})',
        1,
    )
    old_live = """    if live:
        session = _session(); raw = lambda url: raw_http(session,url)
    out = Path(output or PROJECT / manifest()[\"continuation\"][\"working_output\"]); out.mkdir(parents=True,exist_ok=True)
    lock, stale = lock_output(out)
    try: return collect(out,raw,scope,live,stale)
    finally: lock.unlink(missing_ok=True)
"""
    new_live = """    browser = None
    if live:
        browser = ChromeTransport()
        browser.__enter__()
        raw = browser.raw
    out = Path(output or PROJECT / manifest()[\"continuation\"][\"working_output\"]); out.mkdir(parents=True,exist_ok=True)
    lock, stale = lock_output(out)
    try: return collect(out,raw,scope,live,stale)
    finally:
        try:
            if browser is not None: browser.__exit__(None, None, None)
        finally:
            lock.unlink(missing_ok=True)
"""
    if old_live not in source:
        raise ValueError("v1 runner live transport anchor not found")
    source = source.replace(old_live, new_live, 1)
    source = source.replace('exported["columns"]!=64', 'exported["columns"]!=65')
    source = source.replace('result["columns"]!=64', 'result["columns"]!=65')
    runner.write_text(source, encoding="utf-8")
    frozen = OUT / "frozen/scripts/modules"
    shutil.copy2(ROOT / "scripts/modules/notion_schema.json", frozen / "notion_schema.json")
    shutil.copy2(ROOT / "scripts/modules/notion_export.py", frozen / "notion_export.py")
    shutil.copy2(ROOT / "scripts/modules/permkrai_chrome_transport.py", frozen / "permkrai_chrome_transport.py")
    scope = json.loads((V1 / "scope.json").read_text(encoding="utf-8"))
    scope.update(
        {
            "scope_version": "20260926_v2_headed_chrome",
            "transport": "playwright_channel_chrome_headed_quic",
            "csv_scalar_columns": 65,
            "scope_origin": "v1 reduced-first scope; transport and schema upgraded",
        }
    )
    (OUT / "scope.json").write_text(
        json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "INSTRUCTIONS.md").write_text(
        """# Пермская краевая библиотека: reduced-first, headed Chrome v2

Вызов использует только headed Google Chrome через Playwright `channel=chrome`
с QUIC и чистым временным профилем. Он не использует профиль пользователя,
cookies, логин, форму, proxy/VPN или обход защит. Разрешены только HTTPS GET к
`lib.permkrai.ru`, после robots.txt и с его crawl-delay. Сначала scope reduced:
Пермская губерния и уезды × 6 ключевых слов; 294-запросный scope требует
отдельного решения. Полный текст/HTML карточки, сырьё шифров и дат остаются в
`records_full.jsonl`; file/image URL маппятся в 63/19. CSV-кандидаты содержат
65 скалярных полей. `ready_for_import=false`, Notion только через локальный
мост.

    python -B output/permkrai_catalog_full_handoff_20260926_v2/run_catalog.py --perm-only
""",
        encoding="utf-8",
    )
    (OUT / "run_loop.ps1").write_text(
        """$ErrorActionPreference = 'Continue'
$root = 'D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив'
Set-Location $root
for ($i = 1; $i -le 100; $i++) {
  & python -B 'output/permkrai_catalog_full_handoff_20260926_v2/run_catalog.py' --perm-only
  if ($LASTEXITCODE -ne 3) { break }
  Start-Sleep -Seconds 15
}
""",
        encoding="utf-8",
    )
    manifest = {
        "package": "permkrai_catalog_full_handoff_20260926_v2",
        "source": "permkrai",
        "network": "not_run",
        "ready_for_import": False,
        "project_files": hashes(OUT / "frozen"),
        "package_files": hashes(OUT),
        "continuation": {
            "working_output": "output/permkrai_catalog_full_20260926_v2_permonly",
            "exit_3_only": "same command may resume after request_budget",
            "exit_2": "partial stop; no automatic retry",
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checked(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib.util; p=r'{}'; s=importlib.util.spec_from_file_location('permkrai_v2',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert m.verify()".format(runner),
        ],
        ROOT,
    )
    validation = checked([sys.executable, "-B", str(runner), "--offline-self-test"], ROOT)
    data = json.loads(validation.stdout.splitlines()[-1])
    if not data["passed"] or data["columns"] != 65:
        raise RuntimeError("v2 offline self-test failed: " + validation.stdout)
    result = {
        "network": "not_run",
        "frozen_verify": True,
        "offline_self_test": data,
        "manifest_sha256": sha(OUT / "manifest.json"),
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
