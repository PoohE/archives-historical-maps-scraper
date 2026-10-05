# -*- coding: utf-8 -*-
"""ГАПК (Государственный архив Пермского края): сбор описей картографических фондов.

Источник: `archives.permkrai.ru` (портал «Архивы Прикамья»). `robots.txt` — `Disallow:` пустой,
запретов нет. ⚠️ Портал геоблокирует нероссийские IP: TCP из VPN-туннеля не устанавливается,
поэтому ходим браузером пользователя через CDP (`scripts_rosarchive/cdp.py`), своя вкладка.

Что собираем (разведка 05.10):
  ф. 279 «Коллекция планов, карт и чертежей губернской чертежной, межевой комиссии и Пермского
         земельно-устроительного отряда», 1675–1919, 7 описей — прямой аналог ГАСО ф. 259:
         оп. 1 — Верхотурский, Екатеринбургский, Ирбитский, Камышловский, Красноуфимский,
                 Кунгурский, Осинский уезды (1 150 дел);
         оп. 2 — Оханский, Пермский уезды, план г. Перми работы А. Грубера;
         оп. 3 — Соликамский, Усольский, Чердынский, Камышловский, Шадринский уезды;
  ф. 716 «Архивная коллекция картографических документов», 1741–1986.

Устройство: /archive1/funds/<fund_id> → ссылки /archive1/inventory/<opis_id> → таблица дел
(колонки: Номер, Заголовок, Крайние даты, Кол-во листов), пагинация `?page=N` по 20 строк,
счётчик «Показаны записи A-B из N».

Заголовок дела несёт готовые поля каталога: тип плана, объект, уезд, землемера, технику.

Запуск:
    python collect_gapk_maps.py --funds 279,716
Состояние пишется после каждой страницы, повторный запуск продолжает с места обрыва.
"""
import argparse
import csv
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts_rosarchive"))
from cdp import fetch  # noqa: E402
from parsing import parse_scale, parse_tech  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://archives.permkrai.ru"
ROOT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
OUT = ROOT / "output" / "gapk_maps_20261005"
PAUSE = 2.5

# фонды: номер → id на портале (разведка 05.10)
FUNDS = {"279": "114880", "716": "166730"}

UEZD = re.compile(
    r"(Верхотурск|Екатеринбургск|Ирбитск|Камышловск|Красноуфимск|Кунгурск|Осинск|Оханск|"
    r"Пермск|Соликамск|Усольск|Чердынск|Шадринск)\w*\s+уезд", re.I)
CITY = re.compile(r"\bг(?:ород)?\.?\s*(Перм\w+|Верхотурь\w+|Кунгур\w*|Соликамск\w*|Чердын\w+|"
                  r"Оса\b|Оханск\w*|Ирбит\w*)", re.I)
MAP_SUBJ = re.compile(r"план|карт|чертеж|чертёж|атлас|съемк|съёмк|профил", re.I)
YEARS = re.compile(r"(\d{4})\s*[–—-]\s*(\d{4})")

COLS = ["source", "archive", "fund", "opis", "opis_title", "delo", "title",
        "year_from", "year_to", "sheets", "uezd", "city", "scale_raw", "scale_denom",
        "technique", "is_map", "url", "needs_human", "needs_human_reason"]


def soup(url: str, wait: float = 6.0) -> BeautifulSoup:
    html, _ = fetch(url, wait=wait, own_tab=True)
    return BeautifulSoup(html, "lxml")


def opis_list(fund_id: str) -> list[tuple[str, str, str]]:
    """(opis_id, номер описи, заголовок) со страницы фонда."""
    so = soup(f"{BASE}/archive1/funds/{fund_id}")
    out, seen = [], set()
    for a in so.find_all("a", href=True):
        m = re.search(r"/archive1/inventory/(\d+)", a["href"])
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        row = a.find_parent("tr")
        num = ""
        if row:
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if cells:
                num = cells[0]
        out.append((m.group(1), num or str(len(out) + 1), title[:220]))
    return out


def cases_page(opis_id: str, page: int) -> tuple[list[dict], int]:
    """Дела одной страницы описи + объявленное «из N»."""
    url = f"{BASE}/archive1/inventory/{opis_id}" + (f"?page={page}" if page > 1 else "")
    so = soup(url)
    total = 0
    m = re.search(r"Показаны записи[^\d]*\d+\s*[-–]\s*\d+\s*из\s*([\d\s\u00a0]+)",
                  so.get_text(" ", strip=True))
    if m:
        total = int(re.sub(r"[\s\u00a0]", "", m.group(1)))
    rows = []
    tbl = so.find("table")
    for tr in (tbl.select("tbody tr") if tbl else []):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        if len(cells) < 2 or not any(cells):
            continue
        rows.append({"delo": cells[0], "title": cells[1],
                     "dates": cells[2] if len(cells) > 2 else "",
                     "sheets": cells[3] if len(cells) > 3 else "",
                     "url": url})
    return rows, total


def build(fund: str, opis_num: str, opis_title: str, r: dict) -> dict:
    title = r["title"]
    y = YEARS.search(r.get("dates") or "")
    uezd = sorted({m.group(0) for m in UEZD.finditer(title)})
    city = sorted({m.group(1) for m in CITY.finditer(title)})
    raw, den = parse_scale(title)
    is_map = bool(MAP_SUBJ.search(title))
    reasons = []
    if not uezd and not city:
        reasons.append("territory_not_in_title")
    if not is_map:
        reasons.append("subject_not_cartographic")
    return {
        "source": "gapk", "archive": "ГАПК", "fund": fund, "opis": opis_num,
        "opis_title": opis_title, "delo": r["delo"], "title": title,
        "year_from": y.group(1) if y else "", "year_to": y.group(2) if y else "",
        "sheets": r.get("sheets", ""), "uezd": "; ".join(uezd), "city": "; ".join(city),
        "scale_raw": raw, "scale_denom": den, "technique": parse_tech(title),
        "is_map": "true" if is_map else "false", "url": r["url"],
        "needs_human": "true" if reasons else "false",
        "needs_human_reason": "; ".join(reasons),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", default="279,716")
    ap.add_argument("--max-pages", type=int, default=0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    state_path, recs_path = OUT / "state.json", OUT / "records.jsonl"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    for fund in [x.strip() for x in args.funds.split(",") if x.strip()]:
        if fund not in FUNDS:
            print(f"ф.{fund}: нет id, пропуск")
            continue
        print(f"\n=== фонд {fund}")
        opisi = opis_list(FUNDS[fund])
        print(f"   описей: {len(opisi)}")
        time.sleep(PAUSE)
        for opis_id, opis_num, opis_title in opisi:
            key = f"{fund}/{opis_num}"
            if state.get(key, {}).get("status") == "complete":
                print(f"   оп.{opis_num}: уже собрана")
                continue
            page = state.get(key, {}).get("pages_done", 0) + 1
            total, prev = state.get(key, {}).get("total", 0), set()
            while True:
                if args.max_pages and page > args.max_pages:
                    break
                try:
                    rows, tot = cases_page(opis_id, page)
                except Exception as e:
                    print(f"   оп.{opis_num} стр.{page}: {type(e).__name__} — стоп")
                    break
                total = tot or total
                ids = {r["delo"] for r in rows}
                if not rows or (ids and ids == prev):
                    state[key] = {"pages_done": page - 1, "total": total, "status": "complete"}
                    break
                prev = ids
                with recs_path.open("a", encoding="utf-8") as fh:
                    for r in rows:
                        fh.write(json.dumps(build(fund, opis_num, opis_title, r),
                                            ensure_ascii=False) + "\n")
                state[key] = {"pages_done": page, "total": total, "status": "running"}
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
                if page == 1 or page % 10 == 0:
                    print(f"   оп.{opis_num}: стр.{page}, всего дел {total}")
                if total and page * 20 >= total:
                    state[key]["status"] = "complete"
                    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
                    print(f"   оп.{opis_num}: ЗАВЕРШЕНА ({total} дел)")
                    break
                page += 1
                time.sleep(PAUSE)
            time.sleep(PAUSE)

    rows = [json.loads(x) for x in recs_path.read_text(encoding="utf-8").splitlines()
            if x.strip()] if recs_path.exists() else []
    with (OUT / "records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    rep = {
        "source": "gapk", "archive": "ГАПК", "records": len(rows),
        "by_fund": dict(Counter(r["fund"] for r in rows)),
        "by_uezd": dict(Counter(u for r in rows for u in r["uezd"].split("; ") if u).most_common(15)),
        "is_map": sum(1 for r in rows if r["is_map"] == "true"),
        "with_scale": sum(1 for r in rows if r["scale_denom"]),
        "with_year": sum(1 for r in rows if r["year_from"]),
        "needs_human": sum(1 for r in rows if r["needs_human"] == "true"),
        "ready_for_import": False,
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
