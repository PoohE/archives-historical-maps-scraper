"""Снять URL и содержимое УЖЕ ОТКРЫТОЙ пользователем вкладки (ничего не открывая само).

Нужно, чтобы увидеть рабочий вид страницы поиска: какие параметры в адресе и как
размечены результаты. Запрос к серверу делал пользователь, скрипт только читает DOM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gayo_probe import cdp, eval_in  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "gayo_probe"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    need = sys.argv[1] if len(sys.argv) > 1 else "yar-archives"
    OUT.mkdir(parents=True, exist_ok=True)
    tabs = [t for t in cdp("/json/list") if t.get("type") == "page"]
    for t in tabs:
        print(f"- {t['title'][:60]!r} {t['url'][:150]}")
    hit = next((t for t in tabs if need in t["url"]), None)
    if not hit:
        print(f"\nвкладки с «{need}» нет")
        return 1
    print(f"\nЧИТАЮ: {hit['url']}")
    html = eval_in(hit["webSocketDebuggerUrl"], "document.documentElement.outerHTML")
    text = eval_in(hit["webSocketDebuggerUrl"], "document.body.innerText")
    (OUT / "open_tab.html").write_text(html or "", encoding="utf-8")
    (OUT / "open_tab.txt").write_text(text or "", encoding="utf-8")
    (OUT / "open_tab_url.json").write_text(json.dumps({"url": hit["url"]}, ensure_ascii=False),
                                           encoding="utf-8")
    print(f"html {len(html or '')} симв., текст {len(text or '')} симв. → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
