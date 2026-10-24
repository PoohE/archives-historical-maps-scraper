"""Свердловская ОУНБ им. Белинского: электронная библиотека (DSpace) — прогон.

Почему источник в проекте: Екатеринбургский, Верхотурский, Ирбитский, Камышловский,
Красноуфимский и Шадринский уезды — это ПЕРМСКАЯ губерния, и краеведческий фонд Белинки
держит её земские издания, памятные книжки и ежегодники.

Разведка 21.10.2026:
  * сайт библиотеки — `book.uraic.ru` (robots содержит только `Host:`, запретов нет),
    электронная библиотека — отдельный хост **`elib.uraic.ru`**, это **DSpace**
    (`/simple-search?query=`, `/handle/123456789/<N>`, `/browse?type=collection`);
    robots у `elib` пустой — запретов нет;
  * ⚠️ **TLS в коде НЕ ослабляем**: `book.uraic.ru` редиректит http→https, а сертификат
    выпущен УЦ, которого нет в доверенных (`CERTIFICATE_VERIFY_FAILED`). По правилу
    проекта исключение подтверждается вручную в браузере, поэтому работаем через
    отладочную копию Chrome по CDP, а не `verify=False`;
  * ⚠️ `/community-list` и `/rest/items`, `/oai/request` отдают пустой ответ (39 и 0
    байт) — REST и OAI выключены. Рабочие точки: `/simple-search` и `/handle/<id>`;
  * профильная коллекция внутри «1. Краеведение Урала» (`/handle/123456789/3`) —
    **«Земские издания Пермской губернии»**, рядом «Редкие книги об Урале».

Запуск:
    python -B scripts_uraic/uraic_sweep.py --limit 3
    python -B scripts_uraic/uraic_sweep.py
"""
from __future__ import annotations

import argparse
import csv
import html as H
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from cdp_fetch import Browser  # noqa: E402

OUT = ROOT / "output" / "uraic_20261021"
HOST = "http://elib.uraic.ru"
DELAY = 2.0
RPP = 50

# Пермская губерния и её уезды/города (Белинка — екатеринбургская, поэтому упор на Урал)
# ⚠️ DSpace ищет по КОНЪЮНКЦИИ всех слов запроса: «карта Пермской губернии» даёт 0,
# тогда как «Пермской губернии» — 10 записей. Поэтому запросы короткие и
# территориальные, а жанр отбирает уже гейт по заголовку. Проверено на пробе 21.10.
QUERIES = [
    "Пермской губернии", "Пермская губерния", "Пермской",
    "Екатеринбургский", "Верхотурский", "Ирбитский", "Камышловский",
    "Красноуфимский", "Шадринский", "Кунгурский", "Соликамский",
    "Чердынский", "Оханский", "Осинский",
    "Екатеринбург", "Верхотурье", "Ирбит", "Шадринск", "Кунгур",
    "Соликамск", "Чердынь", "Камышлов", "Красноуфимск",
    "карта", "атлас", "план города", "межевание", "населенных мест",
    "памятная книжка", "адрес-календарь", "статистический",
]
HANDLE = re.compile(r"/handle/(\d+/\d+)")
# Метаданные карточки DSpace лежат в таблице «ключ / значение»
META_KEYS = ("dc.title", "dc.date.issued", "dc.publisher", "dc.contributor.author",
             "dc.identifier", "dc.description", "dc.subject", "dc.type",
             "Название", "Дата", "Издательство", "Авторы", "Описание", "Тип")


def titles_from(doc: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r'href="(/handle/\d+/\d+)"[^>]*>(.*?)</a>', doc, re.S):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", H.unescape(m.group(2)))).strip()
        if t and len(t) > 2:
            out.append((m.group(1), t[:300]))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-pages", type=int, default=8)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    qs = QUERIES[: args.limit] if args.limit else QUERIES
    br = Browser(HOST + "/")
    found: dict[str, dict] = {}
    dst = OUT / "uraic_items.jsonl"
    if dst.exists():
        for ln in dst.open(encoding="utf-8"):
            try:
                r = json.loads(ln)
                found[r["handle"]] = r
            except Exception:  # noqa: BLE001, S112
                continue
        print(f"уже собрано ранее: {len(found)}")

    for i, q in enumerate(qs, 1):
        new_q = 0
        for page in range(args.max_pages):
            params = {"query": q, "rpp": str(RPP), "start": str(page * RPP)}
            doc = br.render(f"{HOST}/simple-search?{urllib.parse.urlencode(params)}",
                            wait=9) or ""
            pairs = titles_from(doc)
            new = 0
            for h, t in pairs:
                hid = HANDLE.search(h).group(1)
                if hid in found:
                    continue
                found[hid] = {"handle": hid, "zagolovok": t,
                              "url": f"{HOST}/handle/{hid}", "zapros": q,
                              "istochnik": "Свердловская ОУНБ им. Белинского (elib.uraic.ru)"}
                new += 1
            new_q += new
            time.sleep(DELAY)
            if not pairs or new == 0:
                break
        print(f"  {i:>3}/{len(qs)} {q[:44]:<46} +{new_q} (всего {len(found)})", flush=True)

    # обход профильной коллекции «Краеведение Урала» целиком
    for coll in ("123456789/3",):
        doc = br.render(f"{HOST}/handle/{coll}", wait=9) or ""
        for h, t in titles_from(doc):
            hid = HANDLE.search(h).group(1)
            if hid not in found:
                found[hid] = {"handle": hid, "zagolovok": t,
                              "url": f"{HOST}/handle/{hid}",
                              "zapros": f"коллекция {coll}",
                              "istochnik": "Свердловская ОУНБ им. Белинского (elib.uraic.ru)"}
        print(f"  коллекция {coll}: всего {len(found)}")
    br.close()

    rows = sorted(found.values(), key=lambda r: r["zagolovok"])
    with dst.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    if rows:
        with (OUT / "uraic_items.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"\nзаписей собрано: {len(rows)}")
    print(f"→ {OUT / 'uraic_items.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
