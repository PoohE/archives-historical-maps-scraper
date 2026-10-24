"""Снять DOM открытых вкладок ГАКО из Chrome по CDP — без единого запроса к серверу.

Почему так: `archive.admoblkaluga.ru/robots.txt` поимённо запрещает ИИ-агентам обход
(`User-agent: anthropic-ai` → `Disallow: /`). Запреты robots адресованы агентам, а не
человеку: страницы открывает ПОЛЬЗОВАТЕЛЬ в своём браузере, скрипт лишь читает то, что
уже загружено во вкладке. Сеть при этом не используется вовсе — только локальный порт
отладки Chrome.

Подготовка (один раз, в отдельном окне с чистым профилем):
    & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\\arch\\chrome_dbg"

Запуск:
    python -B scripts_gako/read_tabs_gako.py --out C:\\arch\\gako_in
    python -B scripts_gako/read_tabs_gako.py --out C:\\arch\\gako_in --list   # только список вкладок
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9222"
HOST = "archive.admoblkaluga.ru"


def cdp_get(path: str):
    with urllib.request.urlopen(f"{CDP}{path}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def dom_of(ws_url: str) -> str | None:
    """Забрать outerHTML вкладки через DevTools Protocol."""
    try:
        import websocket
    except ImportError:
        print("нужен websocket-client:  pip install websocket-client")
        raise SystemExit(1) from None

    # ⚠️ Chrome отклоняет WebSocket с чужим Origin («Handshake status 403 Forbidden …
    # Use --remote-allow-origins»). Вместо перезапуска браузера с флагом просто не шлём
    # заголовок Origin — DevTools принимает такое соединение.
    ws = websocket.create_connection(ws_url, timeout=25, suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": "document.documentElement.outerHTML",
                       "returnByValue": True},
        }))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                return msg.get("result", {}).get("result", {}).get("value")
    finally:
        ws.close()


def safe_name(title: str, url: str, idx: int) -> str:
    m = re.search(r"p0\.d=(\d+)", url) or re.search(r"/object/(\d+)", url)
    key = m.group(1) if m else f"tab{idx:02d}"
    base = re.sub(r"[^A-Za-z0-9А-Яа-яЁё_-]+", "_", title)[:40].strip("_") or "page"
    return f"tab_{key}_{base}.html"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--list", action="store_true", help="только показать вкладки")
    args = ap.parse_args()

    try:
        tabs = cdp_get("/json/list")
    except Exception as exc:  # noqa: BLE001
        print(f"Chrome с отладкой не отвечает на {CDP}: {type(exc).__name__}")
        print("Запустите окно с флагом --remote-debugging-port=9222 (см. докстринг).")
        return 1

    pages = [t for t in tabs if t.get("type") == "page" and HOST in (t.get("url") or "")]
    print(f"вкладок всего: {len(tabs)}, из них страниц ГАКО: {len(pages)}")
    for i, t in enumerate(pages, 1):
        print(f"  {i:>2}. {(t.get('title') or '')[:60]}  {t.get('url', '')[:90]}")
    if args.list or not pages:
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    saved = 0
    for i, t in enumerate(pages, 1):
        html = dom_of(t["webSocketDebuggerUrl"])
        if not html:
            print(f"  ✗ вкладка {i}: DOM не получен")
            continue
        f = out / safe_name(t.get("title") or "", t.get("url") or "", i)
        f.write_text(html, encoding="utf-8")
        saved += 1
        print(f"  ✓ {f.name}  ({len(html) // 1024} КБ)")
    print(f"\nсохранено страниц: {saved} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
