"""Build the NEB recon-first handoff package without running the network."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/neb_recon_runner.py"


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


def main(package: str) -> None:
    OUT = ROOT / "output" / package
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    if not RUNNER.is_file():
        raise FileNotFoundError("NEB recon runner is absent: " + str(RUNNER))

    OUT.mkdir(parents=True)
    shutil.copy2(RUNNER, OUT / "run_recon.py")
    scope = {
        "package": package,
        "source": "neb",
        "purpose": "recon_first_real_dom_only",
        "network": "not_run",
        "transport": "playwright_channel_chrome_headed_clean_context",
        "allowed_routes": [
            "https://rusneb.ru/robots.txt",
            "https://rusneb.ru/search/?q=карта+Калужская+губерния&access[]=open&catalog[]=Карты",
            "one same-host /catalog/ detail URL discovered in the rendered search DOM",
        ],
        "prohibited": [
            "login", "authorization", "CAPTCHA handling", "cookies/profile reuse",
            "POST", "proxy", "VPN", "Scrapedo", "file/download endpoints", "Notion",
            "canonical Ontology", "field parsing", "full search",
        ],
        "request_budget": 3,
        "selection": {
            "search_query": "карта Калужская губерния",
            "catalog_filter": "Карты",
            "detail": "first same-host /catalog/ URL seen after rendered search stabilizes",
        },
        "robots": {
            "required_before_search": True,
            "on_missing_or_non_text_response": "stop_access_unresolved",
            "on_disallow_search": "stop_robots_disallow_search",
        },
        "render": {
            "wait_ms": 30000,
            "scroll_until_stable_repetitions": 2,
            "max_scrolls": 8,
            "persist": ["robots.txt", "search_rendered.html", "card_rendered.html"],
        },
        "outputs": ["REPORT.json", "requests.jsonl", "raw_html/", "manifest.json"],
        "ready_for_import": False,
    }
    (OUT / "scope.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "INSTRUCTIONS.md").write_text(
        """# НЭБ: recon-first v1

Пакет делает не более трёх GET в новом видимом Chrome-контексте без профиля,
cookies и авторизации: `robots.txt`, одну выдачу карт и одну карточку,
обнаруженную в этой выдаче. Он не заполняет поля, не формирует CSV и не
скачивает файлы. Цель — передать реальный robots и rendered DOM для отдельного
извлечения селекторов.

До выдачи обязателен реальный `robots.txt`. Если robots недоступен, не является
текстом или запрещает `/search/`, пакет останавливается. При 401/403/429,
Cloudflare-челлендже, CAPTCHA, ошибке транспорта, отсутствии карточки или
нестабильном рендере он сохраняет полученное evidence и завершает работу без
повторов. Scrapedo, proxy/VPN, вход и любые обходы не используются.

```powershell
python -B output/""" + package + """/run_recon.py
```

После запуска проверить `REPORT.json`, `requests.jsonl`, `manifest.json` и
`raw_html/`. Код 0 означает только завершённый recon; это не приёмка источника
и не разрешение на полный сбор или импорт.
""",
        encoding="utf-8",
    )
    manifest = {
        "package": package,
        "network": "not_run",
        "ready_for_import": False,
        "package_files": hashes(OUT),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation = checked([sys.executable, "-B", str(OUT / "run_recon.py"), "--offline-self-test"], ROOT)
    data = json.loads(validation.stdout.splitlines()[-1])
    if data["network"] != "not_run" or data["raw_files"] != 3 or data["status"] != "completed":
        raise RuntimeError("offline recon validation failed: " + validation.stdout)
    manifest["package_files"] = hashes(OUT)
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "network": "not_run",
        "runner_compile": True,
        "offline_self_test": data,
        "manifest_sha256": sha(OUT / "manifest.json"),
    }
    (OUT / "LOCAL_VALIDATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a versioned NEB recon handoff")
    parser.add_argument("--package", default="neb_recon_handoff_20260928_v1")
    args = parser.parse_args()
    main(args.package)
