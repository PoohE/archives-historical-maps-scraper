"""ГПИБ (elib.shpl.ru): разведка дерева на предмет картографии по 4 губерниям проекта.

Источник НИКОГДА не прогонялся: числился закрытым robots-ом. Проверка 18.10 показала,
что robots запрещает ровно один путь — `/ru/nodes/search`; дерево `/ru/nodes/<id>`
открыто полностью, поимённых запретов агентам нет. Поиском не пользуемся, идём деревом.

Что делает: обходит заданные узлы вглубь (ограничение по глубине и числу запросов),
собирает заголовки и отмечает совпадения по нашим губерниям и по картографическому
признаку. Это РАЗВЕДКА объёма, а не сбор пакета: решение о полном прогоне принимается
по её результату.

Запуск:
    python -B scripts_gpib/gpib_probe.py --depth 2 --max-requests 150
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "gpib_probe"
HOST = "http://elib.shpl.ru"

# Точки входа: витрина карт, коллекции и иллюстративный материал.
SEEDS = {
    "9516": "Карты, планы, схемы и виды",
    "9502": "Иллюстративный материал",
    "9501": "Коллекции",
}

NODE = re.compile(r'href="(/ru/nodes/(\d+)-[^"]*)"[^>]*>\s*([^<]{3,200})')
CARTO = re.compile(r"\bкарт[аыуеой]\b|\bкарты\b|\bплан\b|\bпланы\b|атлас|чертеж|чертёж"
                   r"|съемк|съёмк|топограф|межев", re.I)
OURS = re.compile(r"Калужск|Смоленск|Ярославск|Пермск|Пермь\b"
                  r"|Ростовск|Углич|Мышкин|Пошехон|Любим|Данилов|Молог|Рыбинск"
                  r"|Вязьм|Гжатск|Дорогобуж|Духовщин|Поречск|Рославл|Сычев|Юхнов"
                  r"|Боровск|Козельск|Малояросл|Медын|Мещовск|Мосальск|Перемышл|Таруc"
                  r"|Соликамск|Чердын|Кунгур|Оса\b|Оханск|Верхотур|Ирбит|Шадринск", re.I)


def fetch(url: str, tries: int = 3) -> str | None:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (i + 1))
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--max-requests", type=int, default=150)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    found: list[dict] = []
    spent = 0
    queue = [(nid, title, 0) for nid, title in SEEDS.items()]

    while queue and spent < args.max_requests:
        nid, parent_title, depth = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        htm = fetch(f"{HOST}/ru/nodes/{nid}")
        spent += 1
        time.sleep(args.delay)
        if not htm:
            continue
        for href, child_id, raw in NODE.findall(htm):
            title = html.unescape(raw).strip()
            if child_id in seen or not title or "Электронная библиотека" in title:
                continue
            rec = {
                "id": child_id, "title": title, "url": HOST + href,
                "parent": parent_title, "depth": depth + 1,
                "carto": bool(CARTO.search(title)), "ours": bool(OURS.search(title)),
            }
            found.append(rec)
            # на первом уровне заходим во ВСЕ узлы (заголовок раздела ничего не обещает:
            # карты наших губерний могут лежать в «Материалах архивных комиссий»),
            # глубже — только в релевантные, иначе обход уходит в книжные тома
            if depth + 1 < args.depth and (depth == 0 or rec["carto"] or rec["ours"]):
                queue.append((child_id, title, depth + 1))

    uniq = {r["id"]: r for r in found}
    (OUT / "nodes.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in uniq.values()),
        encoding="utf-8")

    carto = [r for r in uniq.values() if r["carto"]]
    ours = [r for r in uniq.values() if r["ours"]]
    both = [r for r in uniq.values() if r["carto"] and r["ours"]]
    print(f"запросов: {spent}, узлов найдено: {len(uniq)}")
    print(f"  с картографическим признаком: {len(carto)}")
    print(f"  с упоминанием наших территорий: {len(ours)}")
    print(f"  и то и другое: {len(both)}")
    print("\nнаши территории + картография:")
    for r in both[:30]:
        print(f"  · {r['title'][:95]}")
        print(f"    {r['url']}")
    if not both:
        print("  (совпадений нет)")
    print(f"\n→ {OUT / 'nodes.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
