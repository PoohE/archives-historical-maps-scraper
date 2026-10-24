"""Разведка Архивного фонда Ярославской области (af.yar-archives.ru) через браузер пользователя.

Сайт закрыт WAF для всех нероссийских адресов: 403 и напрямую, и через Jina (проверено
14.10.2026) — robots.txt оттуда не прочитать вовсе. Поэтому единственный маршрут тот же,
что с ГАКО: страницы открывает браузер пользователя (его IP, его сессия), скрипт снимает
уже загруженный DOM по протоколу отладки. Запросов к серверу от себя скрипт не делает.

Запуск (Chrome должен быть поднят с --remote-debugging-port=9222):
    python -B scripts_gayo/gayo_probe.py --robots
    python -B scripts_gayo/gayo_probe.py --search "карта ярославск"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9222"
HOST = "af.yar-archives.ru"
DELAY = 2.5
LOAD_WAIT = 5.0
OUT = Path(__file__).resolve().parents[1] / "output" / "gayo_probe"


def cdp(path: str, method: str = "GET"):
    req = urllib.request.Request(f"{CDP}{path}", method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def open_tab(url: str) -> dict:
    # адрес уходит в query самого CDP → кодировать ЦЕЛИКОМ (урок ГАКО: иначе обрыв на первом &)
    return cdp("/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")


def close_tab(tid: str) -> None:
    try:
        cdp(f"/json/close/{tid}")
    except Exception:  # noqa: BLE001, S110
        pass


def eval_in(ws_url: str, expr: str):
    import websocket

    ws = websocket.create_connection(ws_url, timeout=40, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                return msg.get("result", {}).get("result", {}).get("value")
    finally:
        ws.close()


def fetch(url: str, expr: str = "document.documentElement.outerHTML",
          wait: float = LOAD_WAIT):
    tab = open_tab(url)
    tid = tab.get("id")
    try:
        time.sleep(wait)
        return eval_in(tab["webSocketDebuggerUrl"], expr)
    finally:
        if tid:
            close_tab(tid)
        time.sleep(DELAY)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", action="store_true")
    ap.add_argument("--search", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--name", default="", help="имя файла для сохранения (без него — page.html)")
    ap.add_argument("--text", action="store_true", help="сохранить ещё и видимый текст")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.robots:
        txt = fetch(f"https://{HOST}/robots.txt", "document.body.innerText", wait=3.0)
        print("=== robots.txt ===")
        print(txt or "(пусто)")
        (OUT / "robots.txt").write_text(txt or "", encoding="utf-8")

    url = args.url
    if args.search:
        q = urllib.parse.quote_plus(args.search)
        url = (f"https://{HOST}/archive/search?q={q}"
               f"&fnum=&onum=&dnum=&from=&to=&archive=&page=1")
    if url:
        html = fetch(url)
        if not html:
            print("DOM не получен")
            return 1
        name = args.name or ("search.html" if args.search else "page.html")
        (OUT / name).write_text(html, encoding="utf-8")
        print(f"сохранено: {OUT / name}  ({len(html)} символов)"
              + ("  ⚠️ КАПЧА" if "form-captcha" in html else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
