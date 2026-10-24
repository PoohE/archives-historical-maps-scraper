"""Смоленская ОУНБ им. А. Т. Твардовского: обход электронной библиотеки `elib.smolensklib.ru`.

⚠️ МАРШРУТ (разведан 22.10.2026). Поиском пользоваться НЕЛЬЗЯ: `robots.txt` библиотеки
запрещает ровно два пути — `/account` и `/search/result`, и второй из них это и есть
выдача поиска (форма расширенного поиска постит именно туда; `/search2` из атрибута
`action` отвечает 404 — это вложенная форма). Зато открыт раздел ПОСТУПЛЕНИЙ
`/main/last?page=N` — те же записи, только листаются по дате загрузки.

ПОЧЕМУ ЭТО ВЫГОДНО: строка листинга несёт ПОЛНОЕ библиографическое описание, а не
только заголовок — выходные данные, год, объём, режим доступа и прямую ссылку на PDF:

    «Памятная книжка Смоленской губернии на 1858 год [Электронный ресурс]. — Электрон.
    текстовые дан. (1 файл : 22,2 Мб). — Смоленск: Тип. Губ. правления, 1858 — 270 с.
    … — Режим доступа: http://elib.smolensklib.ru/bd/books/000002901.pdf»

То есть заходить в карточку каждого документа не нужно: 5 508 страниц листинга вместо
55 077 карточек, и гейт получает больше данных, чем дала бы карточка.

⚠️ ИДЁМ С КОНЦА. Сортировка — по дате поступления, новое сверху. Дореволюционные книги
грузились в ЭБ первыми (2012 год), поэтому профильное лежит на ПОСЛЕДНИХ страницах:
на 5508-й — «Историко-статистическое описание Смоленской епархии» 1864 г. и «Памятная
книжка Смоленской губернии на 1858 год». Обход идёт от последней страницы к первой,
чтобы ценное пришло сразу, а газеты и патенты — в конце.

Размер страницы фиксирован: `rows`, `per_page`, `limit` игнорируются, всегда 10.
Фильтр по коллекции через URL не работает (`?collection=books` отдаёт те же газеты),
поэтому коллекция определяется по пути файла: /bd/books/, /bd/gazeta/, /bd/patent_ru/.

Запуск:
    python -B scripts_smolensk/smolensk_sweep.py --limit 5
    python -B scripts_smolensk/smolensk_sweep.py
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "smolensk_20261022"
DST = OUT / "smolensk_items.jsonl"
PAGES = OUT / "pages_done.txt"  # журнал пройденных страниц, см. шапку
HOST = "http://elib.smolensklib.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DELAY = 0.35
POTOKOV = 4  # см. шапку патча: сервер отвечает ~4 с, поток простаивает
STRANIC = 5508  # «Найдено документов: 55 077», по 10 на страницу

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
INFO = re.compile(r'href="(/bd/([^/"]+)/([^"]+?))/info"')
DATA = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
TAGS = re.compile(r"<[^>]+>")


def get(url: str, tries: int = 3) -> str | None:
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3 + 4 * n)
    return None


def clean(s: str) -> str:
    return html.unescape(TAGS.sub(" ", s)).replace("\xa0", " ").strip()


def parse_page(doc: str) -> list[dict]:
    out = []
    for raw in ROW.findall(doc):
        m = INFO.search(raw)
        if not m:
            continue
        put, kollekciya, fajl = m.group(1), m.group(2), m.group(3)
        txt = re.sub(r"\s+", " ", clean(raw))
        # номер записи в общем списке идёт первым числом строки
        nomer = (re.match(r"^\s*(\d+)\b", txt) or [None, ""])[1]
        data = (DATA.search(txt) or [""])[0]
        opis = txt
        if nomer:
            opis = opis[len(nomer):].strip()
        if data:
            opis = opis.replace(data, "").strip()
        # год издания — последний год в выходных данных до объёма
        gody = re.findall(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", opis)
        out.append({
            "nomer": nomer,
            "kollekciya": kollekciya,
            "fajl": fajl,
            "zagolovok": opis.split("[Электронный ресурс]")[0].strip(" .—")[:400],
            "bibl_opisanie": opis[:1200],
            "god": gody[0] if gody else "",
            "gody_vse": ";".join(dict.fromkeys(gody))[:60],
            "dostup": ("по паролю" if "по паролю" in opis
                       else "свободный" if "Свободный доступ" in opis else ""),
            "url": f"{HOST}{put}/info",
            "url_fajla": f"{HOST}{put}",
            "data_postupleniya": data,
            "istochnik": "Смоленская ОУНБ им. А. Т. Твардовского (elib.smolensklib.ru)",
        })
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="сколько страниц взять (с конца)")
    ap.add_argument("--ot", default="auto",
                    help="стартовая страница; auto — продолжить с места остановки")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if DST.exists():
        for ln in DST.open(encoding="utf-8", errors="replace"):
            try:
                done.add(json.loads(ln)["url"])
            except Exception:  # noqa: BLE001, S112
                continue
    print(f"уже собрано: {len(done)}", flush=True)

    # ⚠️ Пройденные страницы берём ИЗ ЖУРНАЛА, а не из объёма jsonl: счёт по числу
    # записей врёт, если файл пишут два процесса сразу (поймано 22.10).
    proidennye: set[int] = set()
    if PAGES.exists():
        proidennye = {int(x) for x in PAGES.read_text(encoding="utf-8").split() if x.isdigit()}
    print(f"страниц пройдено: {len(proidennye)} из {STRANIC}", flush=True)

    # с конца: старые поступления = дореволюционные книги
    if str(args.ot) == "auto":
        pages = [p for p in range(STRANIC, 0, -1) if p not in proidennye]
    else:
        pages = [p for p in range(int(args.ot), 0, -1) if p not in proidennye]
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        print("все страницы пройдены")
    else:
        print(f"в работе {len(pages)} страниц, начиная с {pages[0]}", flush=True)

    novyh = 0
    zamok = threading.Lock()
    schet = {"i": 0}
    plog = PAGES.open("a", encoding="utf-8")
    fh = DST.open("a", encoding="utf-8")

    def rabota(p: int) -> None:
        nonlocal novyh
        doc = get(f"{HOST}/main/last?page={p}")
        time.sleep(DELAY)
        if not doc:
            print(f"  стр. {p} — не открылась", flush=True)
            return
        rows = parse_page(doc)
        with zamok:
            schet["i"] += 1
            i = schet["i"]
            for r in rows:
                if r["url"] in done:
                    continue
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                done.add(r["url"])
                novyh += 1
            fh.flush()
            plog.write(f"{p}\n")
            plog.flush()
            if i % 50 == 0 or i <= 3 or i == len(pages):
                obr = rows[0]["zagolovok"][:58] if rows else "—"
                print(f"  {i:>5}/{len(pages)} стр.{p:<5} +{len(rows):<3} всего {len(done):>6}  {obr}",
                      flush=True)

    with ThreadPoolExecutor(max_workers=POTOKOV) as pool:
        list(pool.map(rabota, pages))
    fh.close()

    plog.close()
    # дедуп по url: параллельные запуски могли записать одну страницу дважды
    vidino: set[str] = set()
    allr = []
    for ln in DST.open(encoding="utf-8", errors="replace"):
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001, S112
            continue
        if r["url"] in vidino:
            continue
        vidino.add(r["url"])
        allr.append(r)
    # ⚠️ не переписываем рабочий файл на месте: обрыв по таймауту обрежет его
    # на середине строки. Пишем во временный и подменяем атомарно.
    tmp = DST.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in allr:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    # ⚠️ Я.Диск держит файл открытым, пока синхронизирует: WinError 5. Пробуем
    # несколько раз, не вышло — оставляем рабочий файл как есть (данные целы).
    for popytka in range(6):
        try:
            os.replace(tmp, DST)
            break
        except PermissionError:
            time.sleep(2 + 2 * popytka)
    else:
        print(f"⚠️ дедуп отложен: {DST.name} занят (Я.Диск?), временный файл {tmp.name} оставлен")
    if allr:
        cols = sorted({k for r in allr for k in r})
        with (OUT / "smolensk_items.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(allr)
    from collections import Counter
    print(f"\nновых за прогон: {novyh} | всего: {len(allr)}")
    print("по коллекциям:", dict(Counter(r["kollekciya"] for r in allr).most_common(8)))
    print(f"→ {OUT / 'smolensk_items.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
