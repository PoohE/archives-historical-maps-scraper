"""Диагностика: чем именно портал ГАЯО пометил наш профиль браузера.

Задача — ПОНЯТЬ правило (чтобы ему соответствовать), а не обойти его. Смотрим:
статус и заголовки ответа, текст страницы-заслона, куки сайта в нашем профиле,
и одинаково ли ведут себя разные адреса (каталог / карточка фонда / статика).

Запуск: python -B scripts_gayo/diag_captcha.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gayo_harvest as G  # noqa: E402

PROBES = [
    "https://af.yar-archives.ru/archive1/funds?page=74",
    "https://af.yar-archives.ru/archive1/funds",
    "https://af.yar-archives.ru/archive3/funds",
    "https://af.yar-archives.ru/archive1/inventory/10000289992",
    "https://af.yar-archives.ru/robots.txt",
    "https://af.yar-archives.ru/css/af.css",
]

JS = """
(async () => {
  const out = [];
  for (const u of %s) {
    try {
      const r = await fetch(u, {credentials: 'include'});
      const t = await r.text();
      const h = {};
      r.headers.forEach((v, k) => { h[k] = v; });
      out.push({url: u, status: r.status, len: t.length, headers: h,
                captcha: t.includes('form-captcha') || t.includes('Я не робот'),
                snippet: t.replace(/\\s+/g, ' ').slice(0, 300)});
    } catch (e) { out.push({url: u, err: String(e)}); }
  }
  return JSON.stringify({cookie: document.cookie, probes: out});
})()
""" % json.dumps(PROBES)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    tab = G.open_tab("https://af.yar-archives.ru/archive1/funds")
    import time

    time.sleep(4)
    try:
        import websocket

        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=90,
                                         suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": JS, "awaitPromise": True,
                                       "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                break
        raw = msg.get("result", {}).get("result", {}).get("value")
        ws.close()
    finally:
        if tab.get("id"):
            G.close_tab(tab["id"])

    if not raw:
        print("ответ пуст:", json.dumps(msg, ensure_ascii=False)[:800])
        return 1
    data = json.loads(raw)
    print("КУКИ сайта в нашем профиле:")
    for c in (data["cookie"] or "").split("; "):
        print("   ", c[:160] if c else "(нет)")
    print()
    for p in data["probes"]:
        if "err" in p:
            print(f"{p['url']}\n    ОШИБКА {p['err']}")
            continue
        print(f"{p['url']}\n    HTTP {p['status']}  len={p['len']}  "
              f"капча={'ДА' if p['captcha'] else 'нет'}")
        for k in ("retry-after", "x-ratelimit-remaining", "x-ratelimit-reset",
                  "server", "cf-ray", "set-cookie", "cache-control", "x-powered-by"):
            if k in p["headers"]:
                print(f"      {k}: {p['headers'][k][:120]}")
        print(f"      {p['snippet'][:220]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
