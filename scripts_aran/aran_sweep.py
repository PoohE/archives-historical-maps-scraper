"""СПбФ АРАН: сбор дел по географическому указателю.

Разведка 21.10.2026:
  * это `ranar.spb.ru` — НЕ `arran.ru` (тот Архив РАН в Москве, другое учреждение);
  * `robots.txt` отсутствует (404) — запретов нет;
  * страницы рисуются Nuxt'ом, сырой HTML отдаёт только меню → снимаем отрисованный
    DOM через CDP (как у РГО и Госкаталога), иначе в `/geo` ноль записей;
  * ⚠️ самый прямой путь — **географический указатель** `/geo`: 361 запись,
    по 60 на страницу, пагинация `?page=N` (фильтр по алфавиту сделан Vue-радио и
    через URL не управляется, но и не нужен — 7 страниц обходятся целиком);
  * страница записи указателя `/geo/<id>` отдаёт ТАБЛИЦУ ДЕЛ с готовыми архивными
    шифрами: «Ф. 3 Оп. 10 б Д. 3» + заголовок дела + хронологические рамки +
    количество листов. Это ровно то, что нужно каталогу, без отдельного обхода описей.

По 4 губерниям проекта в указателе 8 записей: Малоярославец, Молога, Пермь,
Романов (Ярославская губ.), Рыбинск, Смоленск, Соликамск, Ярославль.
⚠️ Калуги, Углича, Вязьмы и прочих в указателе НЕТ — это не пробел сборщика, а
состав указателя: в него попали только пункты, упомянутые в описаниях дел.

Запуск:
    python -B scripts_aran/aran_sweep.py --index-only
    python -B scripts_aran/aran_sweep.py
"""
from __future__ import annotations

import argparse
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
from scope_rules import territories  # noqa: E402

OUT = ROOT / "output" / "aran_20261021"
HOST = "https://ranar.spb.ru"
DELAY = 1.5
# Шифр дела в таблице: «Ф. 3 Оп. 10 б Д. 3», «Ф. 70 Оп. 2 Д. 172»
SHIFR = re.compile(r"Ф\.\s*\d+[^\n]{0,40}?Д\.\s*[\d/\-а-я]+", re.I)
YEARS = re.compile(r"(1[5-9]\d{2}|20[0-2]\d)")


def text_lines(doc: str) -> list[str]:
    b = re.sub(r"<script.*?</script>|<style.*?</style>", "", doc, flags=re.S)
    b = re.sub(r"<[^>]+>", "\n", b)
    out, prev = [], None
    for x in H.unescape(b).splitlines():
        x = x.strip()
        if (x and x != prev and len(x) > 1
                and not x.startswith(("--", ".", "@", "*", "html", "body", "{", "}"))):
            out.append(x)
        prev = x
    return out


def parse_geo_page(doc: str, geo_name: str) -> list[dict]:
    """Дела со страницы записи указателя.

    Таблица идёт строками: id раздела, шифр, заголовок дела, хрон. рамки,
    кол-во листов, примечание — но пустые ячейки пропускаются, поэтому
    привязываемся к ШИФРУ как к началу записи, а не к числу столбцов.
    """
    lines = text_lines(doc)
    start = next((i for i, x in enumerate(lines) if re.match(r"Дела\s*\(\d+\)", x)), None)
    if start is None:
        return []
    chunk = lines[start:]
    cases, cur = [], None
    for x in chunk:
        if SHIFR.search(x):
            if cur:
                cases.append(cur)
            cur = {"shifr": SHIFR.search(x).group(0).strip(), "zagolovok": "",
                   "hron": "", "listov": "", "geo": geo_name}
            continue
        if cur is None:
            continue
        if re.fullmatch(r"\d{6,}", x):           # id раздела описи — пропускаем
            continue
        if re.fullmatch(r"[\d\s,.\-–]{1,24}(?:л\.|п\.)?", x) and cur["zagolovok"]:
            cur["listov"] = cur["listov"] or x
            continue
        if YEARS.search(x) and len(x) < 60 and cur["zagolovok"]:
            cur["hron"] = cur["hron"] or x
            continue
        if x.startswith(("СПбФ АРАН", "Старая версия")):
            break
        cur["zagolovok"] = (cur["zagolovok"] + " " + x).strip()[:700]
    if cur:
        cases.append(cur)
    return cases


def parse_inventory(doc: str, opis: str) -> list[dict]:
    """Перечень дел со страницы описи `/inventory/<id>` — тот же разбор, что у /geo."""
    lines = text_lines(doc)
    start = next((i for i, x in enumerate(lines)
                  if re.match(r"ПЕРЕЧЕНЬ ДЕЛ\s*\(\d+\)", x, re.I)), None)
    chunk = lines[start:] if start is not None else lines
    cases, cur = [], None
    for x in chunk:
        if SHIFR.search(x):
            if cur:
                cases.append(cur)
            cur = {"shifr": SHIFR.search(x).group(0).strip(), "zagolovok": "",
                   "hron": "", "listov": "", "geo": "", "opis": opis}
            continue
        if cur is None or re.fullmatch(r"\d{6,}", x):
            continue
        if re.fullmatch(r"[\d\s,.\-–]{1,24}(?:л\.|п\.)?", x) and cur["zagolovok"]:
            cur["listov"] = cur["listov"] or x
            continue
        if YEARS.search(x) and len(x) < 60 and cur["zagolovok"]:
            cur["hron"] = cur["hron"] or x
            continue
        if x.startswith(("СПбФ АРАН", "Старая версия", "Перейти на страницу")):
            break
        cur["zagolovok"] = (cur["zagolovok"] + " " + x).strip()[:700]
    if cur:
        cases.append(cur)
    return cases


# ⚠️ ГЛАВНОЕ В АРАН — НЕ географический указатель, а две описи фонда 3 (Канцелярия
# АН 1725–1766). Указатель `/geo` даёт по нашим губерниям всего 8 пунктов и почти
# целиком личную переписку; профильное лежит в описях:
#   Оп. 10а «Географические известия по городам и местностям» — 221 ед. хр.,
#     1760–1768: «Географические известия по г. N и его уезду при рапорте из
#     N-ской воеводской канцелярии» — это ответы на академическую географическую
#     анкету, то есть топографические описания территорий. Опись оцифрована (57),
#     есть PDF-указатель.
#   Оп. 10б — продолжение той же серии (дела по Смоленску, Романову,
#     Малоярославцу найдены через указатель именно здесь).
#   Плюс «Научно-организационные материалы Географического департамента».
# ⚠️ «Географических известий» в фонде 3 ДВЕ описи, и вторая лежит на ВТОРОЙ странице
# списка описей фонда (`/stocks/438407147?page=2`) — с тем же названием, поэтому легко
# пропустить. Именно из неё пришли дела по Смоленску, Романову и Малоярославцу,
# найденные через географический указатель (шифры «Ф. 3 Оп. 10 б Д. 3/8/9»).
INVENTORIES = {
    "Ф. 3 Оп. 10а Географические известия по городам и местностям": "438497026",
    "Ф. 3 Оп. 10б Географические известия по городам и местностям": "438497051",
    "Ф. 3 Оп. 9 Научно-организационные материалы Географического департамента": "438497003",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-only", action="store_true")
    ap.add_argument("--inventories", action="store_true",
                    help="обойти описи «Географических известий» (главный маршрут)")
    ap.add_argument("--max-pages", type=int, default=12)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.inventories:
        br = Browser(HOST + "/")
        rows: list[dict] = []
        for title, inv in INVENTORIES.items():
            seen: set[str] = set()
            for page in range(1, args.max_pages + 1):
                url = f"{HOST}/inventory/{inv}" + (f"?page={page}" if page > 1 else "")
                doc = br.render(url, wait=8) or ""
                cases = [c for c in parse_inventory(doc, title) if c["shifr"] not in seen]
                for c in cases:
                    seen.add(c["shifr"])
                    c["inventory_id"] = inv
                    c["url"] = f"{HOST}/inventory/{inv}"
                    c["istochnik"] = "СПбФ АРАН"
                    rows.append(c)
                print(f"  {title[:34]:<36} стр.{page}: +{len(cases)} (всего {len(seen)})",
                      flush=True)
                if not cases:
                    break
                time.sleep(DELAY)
        with (OUT / "aran_inventory_cases.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        if rows:
            with (OUT / "aran_inventory_cases.csv").open("w", encoding="utf-8-sig",
                                                         newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        mine = [r for r in rows if territories(r["zagolovok"])]
        print(f"\nдел в описях: {len(rows)} | по 4 губерниям: {len(mine)}")
        for r in mine[:40]:
            print(f"   {r['shifr']:<22} {r['zagolovok'][:76]}")
        print(f"→ {OUT / 'aran_inventory_cases.csv'}")
        br.close()
        return 0

    br = Browser(HOST + "/")
    # 1. Указатель целиком
    index: dict[str, str] = {}
    for page in range(1, 9):
        doc = br.render(f"{HOST}/geo?page={page}", wait=6) or ""
        new = 0
        for m in re.finditer(r'href="/geo/(\d+)"[^>]*>(.*?)</a>', doc, re.S):
            gid = m.group(1)
            name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", H.unescape(m.group(2)))).strip()
            if name and gid not in index:
                index[gid] = name
                new += 1
        print(f"  указатель, стр.{page}: +{new} (всего {len(index)})", flush=True)
        if new == 0:
            break
        time.sleep(DELAY)
    (OUT / "geo_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    ours = {g: n for g, n in index.items() if territories(n)}
    print(f"\nзаписей указателя: {len(index)} | по 4 губерниям: {len(ours)}")
    for g, n in sorted(ours.items(), key=lambda x: x[1]):
        print(f"   /geo/{g}  {n}")
    if args.index_only:
        br.close()
        return 0

    # 2. Дела по нашим территориям
    rows = []
    for i, (gid, name) in enumerate(sorted(ours.items(), key=lambda x: x[1]), 1):
        doc = br.render(f"{HOST}/geo/{gid}", wait=7) or ""
        cases = parse_geo_page(doc, name)
        for c in cases:
            c["geo_id"] = gid
            c["url"] = f"{HOST}/geo/{gid}"
            c["istochnik"] = "СПбФ АРАН"
            rows.append(c)
        print(f"  {i}/{len(ours)} {name:<28} дел: {len(cases)}", flush=True)
        time.sleep(DELAY)
    br.close()

    with (OUT / "aran_cases.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    if rows:
        with (OUT / "aran_cases.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"\nдел собрано: {len(rows)}")
    print(f"→ {OUT / 'aran_cases.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
