"""Проверить статические и возможные служебные адреса портала ГАЯО.

Пока сессия помечена капчей, динамика закрыта, но статика отдаётся. Ищем карту сайта,
открытые выгрузки или служебный API — они дали бы законный путь без постраничного обхода.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gayo_harvest as G  # noqa: E402

URLS = [
    "https://af.yar-archives.ru/sitemap.xml",
    "https://af.yar-archives.ru/sitemap_index.xml",
    "https://af.yar-archives.ru/sitemap",
    "https://af.yar-archives.ru/api",
    "https://af.yar-archives.ru/api/funds",
    "https://af.yar-archives.ru/opendata",
    "https://www.yar-archives.ru/robots.txt",
    "https://www.yar-archives.ru/sitemap.xml",
]

JS = r"""
(async () => {
  const out = [];
  for (const u of URLS_JSON) {
    try {
      const r = await fetch(u);
      const t = await r.text();
      const flat = t.replace(/\s+/g, ' ').slice(0, 140);
      out.push(`${u}\n    HTTP ${r.status} len=${t.length}` +
               (t.includes('form-captcha') ? ' КАПЧА' : '') + `\n    ${flat}`);
    } catch (e) { out.push(`${u}\n    ОШИБКА ${e}`); }
  }
  return out.join("\n");
})()
""".replace("URLS_JSON", json.dumps(URLS))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    tab = G.open_tab("https://af.yar-archives.ru/css/af.css")
    try:
        time.sleep(3)
        import websocket

        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=90,
                                         suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": JS, "awaitPromise": True,
                                       "returnByValue": True}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 1:
                break
        ws.close()
        res = m.get("result", {}).get("result", {})
        print(res.get("value") or json.dumps(m, ensure_ascii=False)[:900])
    finally:
        if tab.get("id"):
            G.close_tab(tab["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
