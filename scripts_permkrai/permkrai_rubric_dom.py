"""Пермская краевая: добор рубрики «Карты, схемы, планы» из отрисованного DOM.

Открытый вопрос по источнику: обход рубрики `/node/722` давал 25 карточек, тогда как
ветка node_list — 184; отдаёт ли рубрика весь свой состав, проверено не было.

Проверка 18.10 через браузер: портал рвёт обычное TLS-соединение
(`SSL: UNEXPECTED_EOF`), а сама рубрика — React-приложение: в исходном html списка нет,
он появляется только в отрисованном DOM. Карточка выглядит так:
`<a class="elis-catalog-item" href=".../node/<id>" aria-label="<заголовок>">`.

Рубрика отдаёт 41 карточку, прокрутка вниз новых не подгружает — это весь её состав.

Запуск:
    python -B scripts_permkrai/permkrai_rubric_dom.py
"""
from __future__ import annotations

import csv
import html as H
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from cdp_fetch import Browser  # noqa: E402

OUT = ROOT / "output" / "permkrai_rubric_20261018"
RUBRIC = "https://lib.permkrai.ru/node/722"

CARD = re.compile(r'class="elis-catalog-item[^"]*"[^>]*href="[^"]*?/node/(\d+)"'
                  r'[^>]*aria-label="([^"]*)"')
CARD_ALT = re.compile(r'aria-label="([^"]*)"[^>]*href="[^"]*?/node/(\d+)"')
YEAR = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")


def cards(doc: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in CARD.finditer(doc):
        out[m.group(1)] = H.unescape(m.group(2)).strip()
    for m in CARD_ALT.finditer(doc):
        out.setdefault(m.group(2), H.unescape(m.group(1)).strip())
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    br = Browser("https://lib.permkrai.ru/")
    doc = br.render(RUBRIC, wait=8)
    if not doc:
        print("рубрика не получена:", br.last_error)
        return 1
    found = cards(doc)

    # добираем прокруткой: если список ленивый, новые карточки появятся
    ws = br._conn()  # noqa: SLF001
    for _ in range(6):
        ws.send(json.dumps({"id": 20, "method": "Runtime.evaluate",
                            "params": {"expression": "window.scrollTo(0,document.body.scrollHeight)"}}))
        while True:
            if json.loads(ws.recv()).get("id") == 20:
                break
        time.sleep(2.5)
    ws.send(json.dumps({"id": 21, "method": "Runtime.evaluate",
                        "params": {"expression": "document.documentElement.outerHTML",
                                   "returnByValue": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == 21:
            break
    found.update(cards(msg["result"]["result"]["value"]))
    br.close()

    rows = []
    for nid, title in sorted(found.items(), key=lambda kv: kv[1]):
        y = YEAR.search(title)
        rows.append({
            "node_id": nid,
            "zagolovok": title,
            "url": f"https://lib.permkrai.ru/node/{nid}",
            "god": y.group(1) if y else "",
            "istochnik": "Пермская краевая библиотека",
            "rubrika": "Карты, схемы, планы (node/722)",
            "sposob": "portal: DOM рубрики",
        })

    with (OUT / "rubric_cards.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (OUT / "rubric_cards.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"карточек в рубрике: {len(rows)}")
    print(f"→ {OUT / 'rubric_cards.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
