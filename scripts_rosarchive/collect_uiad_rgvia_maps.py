# -*- coding: utf-8 -*-
"""ГИС УИАД: обход описей картографических фондов РГВИА и сбор дел.

Почему обходом описей, а не поиском: поиск портала фразовый и по релевантности
(«карта Калужской губернии» → 11 результатов), полноты не даёт. Обход описи целиком —
даёт, а территорию помечает наш гейт уже на собранном материале.

Маршрут (разведка 04.10, РЕШЕНИЕ_ГИС_УИАД_главный_источник_2026-10-04.md):
  /search/<архив>/<фонд>/            — описи фонда
  /search/<архив>/<фонд>/<опись>/    — дела описи, ?page=N по 20
Доступ: браузер пользователя через CDP (портал геоблокирует нероссийские IP).

Заголовок дела в этих фондах несёт готовые поля каталога: составителя, место и способ
издания, размер листа, масштаб, технику — их и разбираем.

Запуск:
    python collect_uiad_rgvia_maps.py --funds 414,416,417,418,419,420,421,423
    python collect_uiad_rgvia_maps.py --funds 846 --max-pages 50
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

sys.path.insert(0, str(Path(__file__).parent))
from cdp import fetch, fetch_units  # noqa: E402
from parsing import (  # noqa: E402
    MAP_SUBJ, SIZE, TECH, YEAR, parse_scale, split_case)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://online.archives.ru"
RGVIA = "10000000001003"
ROOT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
OUT = ROOT / "output" / "uiad_rgvia_maps_20261004"
IDS = ROOT / "output" / "rosarchive_rgvia_20261004" / "fund_ids.json"
PAUSE = 3.0

TERR = {
    "Калужская": re.compile(
        r"Калуж|Калуг|Боровск|Козельск|Лихвин|Малоярославец|Медынь|Мещовск|Мосальск|"
        r"Перемышл|Таруса|Жиздр|Сухиничи", re.I),
    "Пермская": re.compile(
        r"Перм|Екатеринбург|Ирбит|Камышлов|Красноуфимск|Кунгур|Оса\b|Оханск|Соликамск|"
        r"Чердын|Шадринск|Верхотур", re.I),
    "Смоленская": re.compile(
        r"Смолен|Вязьм|Гжатск|Дорогобуж|Духовщин|Ельн|Поречь|Рославл|Сычевк|Юхнов|Бельск", re.I),
    "Ярославская": re.compile(
        r"Ярослав|Ростов|Рыбинск|Углич|Молог|Мышкин|Данилов|Любим|Пошехон|Романов", re.I),
}

COLS = ["source", "archive", "fund", "fund_title", "opis", "opis_title", "delo", "title",
        "year_from", "year_to", "scale_raw", "scale_denom", "size_cm", "technique",
        "territory", "is_map", "url", "needs_human", "needs_human_reason"]


def soup(url: str, wait: float = 4.0) -> BeautifulSoup:
    html, _ = fetch(url, wait=wait)
    return BeautifulSoup(html, "lxml")


def opis_list(fund_id: str) -> list[tuple[str, str, str]]:
    """Описи фонда: (opis_id, номер, заголовок)."""
    so = soup(f"{BASE}/search/{RGVIA}/{fund_id}/", wait=5)
    out: list[tuple[str, str, str]] = []
    seen = set()
    for a in so.find_all("a", href=True):
        m = re.search(rf"/search/{RGVIA}/{fund_id}/(\d+)/?$", a["href"])
        if not m or m.group(1) in seen:
            continue
        t = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        num = re.search(r"Опись\s+([\w\-/]+)", t)
        if num:
            seen.add(m.group(1))
            out.append((m.group(1), num.group(1), t[:200]))
    return out


def cases_page(fund_id: str, opis_id: str, page: int) -> tuple[list[tuple[str, str, str]], int]:
    """Дела одной страницы описи (с развёрнутыми заголовками) + объявленное «Всего».

    Заголовки в списке обрезаны на сервере; разворачивает их `fetch_units` кликом по
    «Полный/Краткий заголовок» — иначе теряются масштаб, размер листа и техника.
    """
    url = f"{BASE}/search/{RGVIA}/{fund_id}/{opis_id}/" + (f"?page={page}" if page > 1 else "")
    items, total = fetch_units(url, wait=4.5)
    rows = []
    for it in items:
        mm = re.search(rf"/search/{RGVIA}/{fund_id}/{opis_id}/(\d+)/?$", it.get("href", ""))
        if not mm:
            continue
        delo, title = split_case(it.get("text", ""))
        rows.append((mm.group(1), delo, title))
    return rows, total


def build_record(num, fund_id, fund_title, opis_num, opis_title,
                 opis_id, case_id, delo, title) -> dict:
    terr = [k for k, rx in TERR.items() if rx.search(title)]
    years = YEAR.findall(title)
    raw, den = parse_scale(title)
    sz = SIZE.search(title)
    tech = sorted({m.group(0).lower() for m in TECH.finditer(title)})
    is_map = bool(MAP_SUBJ.search(title))
    reasons = []
    if not terr:
        reasons.append("territory_not_in_title")
    if not is_map:
        reasons.append("subject_not_cartographic")
    return {
        "source": "uiad", "archive": "РГВИА", "fund": num, "fund_title": fund_title,
        "opis": opis_num, "opis_title": opis_title, "delo": delo, "title": title,
        "year_from": years[0] if years else "", "year_to": years[-1] if years else "",
        "scale_raw": raw, "scale_denom": den,
        "size_cm": f"{sz.group(1)}x{sz.group(2)}" if sz else "",
        "technique": "; ".join(tech), "territory": "; ".join(terr),
        "is_map": "true" if is_map else "false",
        "url": f"{BASE}/search/{RGVIA}/{fund_id}/{opis_id}/{case_id}",
        "needs_human": "true" if reasons else "false",
        "needs_human_reason": "; ".join(reasons),
    }


def finalize() -> None:
    recs = OUT / "records.jsonl"
    rows = [json.loads(x) for x in recs.read_text(encoding="utf-8").splitlines()
            if x.strip()] if recs.exists() else []
    with (OUT / "records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    rep = {
        "source": "uiad", "archive": "РГВИА", "records": len(rows),
        "with_territory": sum(1 for r in rows if r["territory"]),
        "by_territory": dict(Counter(t for r in rows for t in r["territory"].split("; ") if t)),
        "by_fund": dict(Counter(r["fund"] for r in rows)),
        "with_scale": sum(1 for r in rows if r["scale_denom"]),
        "with_size": sum(1 for r in rows if r["size_cm"]),
        "is_map": sum(1 for r in rows if r["is_map"] == "true"),
        "ready_for_import": False,
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {OUT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", required=True, help="номера фондов через запятую")
    ap.add_argument("--max-pages", type=int, default=0, help="предел страниц на опись (0 — без)")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    ids = json.loads(IDS.read_text(encoding="utf-8"))
    state_path = OUT / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    recs_path = OUT / "records.jsonl"

    for num in [x.strip() for x in args.funds.split(",") if x.strip()]:
        if num not in ids:
            print(f"ф.{num}: нет идентификатора, пропуск")
            continue
        fund_id, fund_title = ids[num]
        print(f"\n=== фонд {num} ({fund_title[:70]})")
        try:
            opisi = opis_list(fund_id)
        except Exception as e:
            print(f"   описи не получены: {type(e).__name__}: {str(e)[:90]}")
            continue
        print(f"   описей: {len(opisi)}")
        time.sleep(PAUSE)
        for opis_id, opis_num, opis_title in opisi:
            key = f"{num}/{opis_num}"
            if state.get(key, {}).get("status") == "complete":
                print(f"   оп.{opis_num}: уже собрана, пропуск")
                continue
            page = state.get(key, {}).get("pages_done", 0) + 1
            total = state.get(key, {}).get("total", 0)
            while True:
                if args.max_pages and page > args.max_pages:
                    break
                try:
                    rows, tot = cases_page(fund_id, opis_id, page)
                except Exception as e:
                    print(f"   оп.{opis_num} стр.{page}: {type(e).__name__} — стоп по описи")
                    break
                total = tot or total
                if not rows:
                    state[key] = {"pages_done": page - 1, "total": total, "status": "complete"}
                    break
                with recs_path.open("a", encoding="utf-8") as fh:
                    for case_id, delo, title in rows:
                        rec = build_record(num, fund_id, fund_title, opis_num, opis_title,
                                           opis_id, case_id, delo, title)
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                state[key] = {"pages_done": page, "total": total, "status": "running"}
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
                if page == 1 or page % 5 == 0:
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

    finalize()


if __name__ == "__main__":
    main()
