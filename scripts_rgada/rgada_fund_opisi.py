"""РГАДА: перечень описей фонда и обход базы ДЕЛ (`rgada.info/poisk`).

Разведано 16.11.2026 при снятии блокера Б-8. У РГАДА три разных уровня, и для каждого
своя ссылка — прежний единый шаблон `rgada.info/dela/(\\d+)/` снимал номер ФОНДА, поэтому
257 ссылок улова сворачивались в один ключ и фонд выглядел как одна карточка.

МАРШРУТ:

1. **Перечень описей фонда** — `poisk/index.php?fund_number=<N>&Sk=<строк>`.
   Таблица из девяти граф: фонд · название фонда · № описи · название описи · хранилище ·
   годы · **кол-во дел** · аннотация · ссылки. Ссылки двух видов:
   `index2.php?str=<фонд>-opis_<N>` — постраничные ОБРАЗЫ описи, и
   `/opisi/<фонд>-opis_<N>.pdf` — та же опись файлом.

2. **База дел** — `poisk/db.php?T1=<термин>&fund_number=<N>&opisanie=<название фонда>&Sk=30&page=<N>`.
   Отдаёт сами дела: № · город · дата · заголовок · сведения о подлиннике. ⚠️ База есть
   НЕ у всех фондов: ф. 271 — 2 790 записей, ф. 281 — 15 596, а у ф. 1209 ответ
   «Нельзя ничего отобразить» — у него только описи, и дела читаются с образов (Vision).
   Параметр `opisanie` обязателен и должен совпадать с названием фонда из перечня;
   при неточном названии страница отвечает пустой выдачей, а не ошибкой.

3. Страницы `poisk/db.php` — ЛИСТАЛКА, а не карточка записи: в улове словаря их 3 036,
   и записью их считать нельзя (отсюда поправка шаблона в `scripts/build_harvest_queue.py`).

Зачем нам: ф. 1209 и ф. 137 (писцовые, дозорные, отказные книги XVI–XVII вв., позиция
Р2 2.24 — в каталоге таких записей ОДНА), ф. 1355 (экономические примечания, 2.25),
ф. 271 оп. 3 (планы заводов и рудников Берг-коллегии, 1721–1819, 2.26).

Запуск:
    python scripts_rgada/rgada_fund_opisi.py opisi 1209 137 1355 271
    python scripts_rgada/rgada_fund_opisi.py dela 271
    python scripts_rgada/rgada_fund_opisi.py dela 271 --term "план"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402

OUT = ROOT / "output" / "rgada_poisk"
HOST = "http://rgada.info"
UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)"}
DELAY = 1.5

TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
HREF = re.compile(r'href="([^"]+)"')
FOUND = re.compile(r"Обнаружено записей:\s*(\d+)")
NOTHING = "Нельзя ничего отобразить"


def plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def get(url: str, tries: int = 3) -> str:
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read().decode("utf-8", "ignore")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if n == tries - 1:
                raise SystemExit(f"{url}\n  не отвечает: {type(e).__name__}") from None
            time.sleep(DELAY * (n + 2))
    return ""


def opisi(fund: str) -> list[dict]:
    """Перечень описей фонда: номер, название, годы, кол-во дел, ссылки на образы и PDF."""
    url = f"{HOST}/poisk/index.php?" + urllib.parse.urlencode({"fund_number": fund, "Sk": "500"})
    html = get(url)
    rows: list[dict] = []
    for tr in TR.findall(html):
        if "opis_" not in tr and "ukaz_" not in tr:
            continue
        cells = TD.findall(tr)
        if len(cells) < 8:
            continue
        txt = [plain(c) for c in cells]
        links = [urllib.parse.unquote(h) for h in HREF.findall(cells[-1])]
        rows.append({
            "fond": txt[0],
            "fond_name": txt[1],
            "opis": txt[2],
            "opis_name": txt[3],
            "hranilishche": txt[4],
            "gody": txt[5],
            "del": txt[6],
            "annotaciya": txt[7][:600],
            "obrazy": next((f"{HOST}/poisk/{x}" for x in links if "index2.php" in x), ""),
            "pdf": next((f"{HOST}{x}" if x.startswith("/") else x for x in links if x.endswith(".pdf")), ""),
        })
    return rows


def dela_count(fund: str, fund_name: str, term: str = "") -> int | None:
    """Сколько дел в базе у фонда: число, или None — базы дел у фонда нет."""
    url = f"{HOST}/poisk/db.php?" + urllib.parse.urlencode(
        {"T1": term, "fund_number": fund, "opisanie": fund_name, "Sk": "10", "page": "1"})
    t = plain(get(url))
    m = FOUND.search(t)
    if m:
        return int(m.group(1))
    return None if NOTHING in t else 0


# Графы таблицы дел у разных фондов РАЗНЫЕ: у ф. 271 это «Опись · Номер ед. хр. ·
# Датировка · Связка · Документ · Заголовок · Колич. листов · Примечание», у ф. 281 —
# «Номер · Город · Дата · Заголовок · Подлинник». Поэтому колонки читаем из шапки,
# а не прибиваем в коде.
# ⚠️ И строки выдачи НЕ закрыты: все записи приходят одним <tr> (у ф. 271 — 243 ячейки
# в одном), поэтому поток ячеек после шапки делим по её длине.
GRAFA = {
    "Опись": "opis", "Номер ед. хр.": "nomer", "Номер": "nomer", "Датировка": "data",
    "Дата": "data", "Город": "gorod", "Связка": "svyazka", "Документ": "dokument",
    "Заголовок": "zagolovok", "Колич. листов": "listov", "Примечание": "primechanie",
    "Подлинник": "podlinnik",
}


def parse_dela_page(html: str) -> list[dict]:
    """Записи дел со страницы выдачи: графы из шапки, поток ячеек делим по её длине."""
    by_row = [[plain(c) for c in TD.findall(tr)] for tr in TR.findall(html)]
    head_i = next((i for i, c in enumerate(by_row) if "Заголовок" in c and len(c) >= 4), None)
    if head_i is None:
        return []
    keys = [GRAFA.get(h, h.lower()) for h in by_row[head_i]]
    flat: list[str] = []
    for row in by_row[head_i + 1:]:
        flat.extend(row)
    out: list[dict] = []
    step = len(keys)
    for i in range(0, len(flat) - step + 1, step):
        rec = dict(zip(keys, flat[i:i + step]))
        if rec.get("zagolovok"):
            out.append(rec)
    return out


def dela(fund: str, fund_name: str, term: str = "", per: int = 30) -> list[dict]:
    """Обход базы дел постранично. Возобновляемый: страницы пишутся сразу, журнал рядом."""
    total = dela_count(fund, fund_name, term)
    if total is None:
        print(f"  у ф. {fund} базы дел нет — читать с образов описи (PDF/Vision)")
        return []
    print(f"  в базе дел: {total} записей, по {per} на страницу")
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"dela_f{fund}{'_' + term if term else ''}.jsonl"
    jrn = OUT / f"dela_f{fund}{'_' + term if term else ''}_pages.txt"
    done = set(jrn.read_text(encoding="utf-8").split()) if jrn.exists() else set()
    rows: list[dict] = []
    pages = (total + per - 1) // per
    with dst.open("a", encoding="utf-8") as f, jrn.open("a", encoding="utf-8") as j:
        for page in range(1, pages + 1):
            if str(page) in done:
                continue
            url = f"{HOST}/poisk/db.php?" + urllib.parse.urlencode(
                {"T1": term, "fund_number": fund, "opisanie": fund_name,
                 "Sk": str(per), "page": str(page)})
            html = get(url)
            got = 0
            for rec in parse_dela_page(html):
                rec["fond"] = fund
                rec["nomer"] = str(rec.get("nomer", "")).lstrip("№ ").strip()
                rec["istochnik"] = "rgada.info/poisk/db.php"
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                rows.append(rec)
                got += 1
            f.flush()
            j.write(f"{page}\n")
            j.flush()
            if page % 10 == 0 or page == pages:
                print(f"    стр. {page}/{pages}, записей за страницу {got}", flush=True)
            time.sleep(DELAY)
    print(f"  → {dst}")
    return rows


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["opisi", "dela"])
    ap.add_argument("funds", nargs="+", help="номера фондов")
    ap.add_argument("--term", default="", help="слово для поиска внутри базы дел")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    for fund in args.funds:
        print(f"\n=== ф. {fund} ===")
        rows = opisi(fund)
        if not rows:
            print("  описей не найдено (проверить номер фонда)")
            continue
        name = rows[0]["fond_name"]
        vsego = sum(int(re.sub(r"\D", "", r["del"]) or 0) for r in rows)
        s_pdf = sum(1 for r in rows if r["pdf"])
        s_obr = sum(1 for r in rows if r["obrazy"])
        print(f"  {name[:70]}")
        print(f"  описей: {len(rows)}, дел по графе: {vsego}, с PDF: {s_pdf}, с образами: {s_obr}")
        dst = OUT / f"opisi_f{fund}.jsonl"
        dst.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                       encoding="utf-8")
        print(f"  → {dst}")
        n = dela_count(fund, name)
        print(f"  база дел: {'нет' if n is None else str(n) + ' записей'}")
        if args.mode == "dela":
            dela(fund, name, args.term)
        time.sleep(DELAY)


if __name__ == "__main__":
    main()
