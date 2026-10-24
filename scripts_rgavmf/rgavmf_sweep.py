"""РГАВМФ: обход поиска по единицам хранения (rgavmf.ru).

⚠️ МАРШРУТ (разведан 24.10.2026). Сайт на Drupal, поиск — обычный GET, браузер не нужен,
robots без запретов, ИИ-агенты поимённо не упомянуты:

    https://rgavmf.ru/search?search_api_fulltext=<запрос>&page=<N>

По 100 единиц хранения на страницу. Каждая запись — блок `<div class="views-row">`:
  * ссылка вида `/fond/3l/fond-3l-opis-23/fond-3l-opis-23-edkhr715` — из неё читается
    ПОЛНЫЙ ШИФР (фонд, опись, единица хранения), отдельное поле для него не нужно;
  * `views-field-field-zagolovok` — полный заголовок единицы хранения.

⭐ ЧЕМ ЭТОТ ИСТОЧНИК УНИКАЛЕН: масштаб, техника исполнения и ФОРМАТ ЛИСТА стоят прямо
в заголовке единицы хранения:

    «Карта Ярославской губернии. Печатная, в красках. Масштаб 1 дюйм = 25 вёрст.
     Формат 365 х 410.»

Ни один другой наш источник так не описывает. В ГПИБ ради тех же сведений пришлось
скачивать сканы и читать картуши зрением; здесь они разбираются регуляркой.

ПРОФИЛЬНЫЕ ФОНДЫ (по пробе):
  * Ф. 3Л — картографический (описи 23, 25): карты губерний, планы городов, сборные
    листы военно-топографической карты Европейской России;
  * Ф. 33 — Низовой округ корабельных лесов: петровские и послепетровские материалы
    по лесам, лашманы, порубки, Пермское отделение. По классификации проекта это
    пространственное описание территории, а не картография;
  * Ф. 19 — лесопильные заводы с картами губерний.

⚠️ ХОСТ НЕ ОТВЕЧАЕТ С НАШЕЙ МАШИНЫ (24.10). `rgavmf.ru` (5.17.30.120) перестал
принимать соединения по 80/443 и с машины, и из песочницы, при этом у пользователя
в браузере сайт открывается. Значит режут не сайт, а наш сетевой путь. Обход —
прокси Jina (`rules/web-access.md`, ступень 2): запрос физически уходит с серверов
Jina и доходит.

⚠️ ОБЯЗАТЕЛЬНО `X-Return-Format: html`. По умолчанию Jina отдаёт markdown, и в нём
ССЫЛОК НЕТ — а весь шифр (фонд, опись, единица хранения) мы читаем из адреса
карточки `/fond/3l/fond-3l-opis-23/fond-3l-opis-23-edkhr934`. Без этого заголовка
из выдачи остаются одни заголовки без привязки к делу.

Прямой маршрут оставлен первой попыткой: как только хост вернётся, обход отключится
сам (`--pryamo` — только прямо, `--jina` — только через прокси).

Запуск:
    python -B scripts_rgavmf/rgavmf_sweep.py --limit 2
    python -B scripts_rgavmf/rgavmf_sweep.py
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "rgavmf_20261024"
DST = OUT / "rgavmf_items.jsonl"
SHAGI = OUT / "shagi_done.txt"
BASE = "https://rgavmf.ru/search"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DELAY = 0.6
JINA = "https://r.jina.ai/"       # обход: запрос уходит с серверов Jina
DELAY_JINA = 3.5                  # без ключа лимит ~20 запросов в минуту
SCRAPEDO = "http://api.scrape.do"
# ⚠️ Признак того, что страница поиска ДОШЛА. Проверять по наличию записей нельзя:
# у «Лихвин», «Оханск», «Романов-Борисоглебск» на сайте честно нет ни одной единицы
# хранения, и такая пустая страница выглядела бы отказом (24.10 так и вышло — три
# запроса бесконечно числились «не достучались»). Маркер — сама форма поиска.
STRANICA_POISKA = "search_api_fulltext"
TOKEN_FILE = (Path.home() / ".claude" / "skills" / "scrapedo-web-scraper"
              / "config" / "token.txt")
MAX_STRANIC = 60  # 6000 единиц на запрос — с запасом

ROW = re.compile(r'<div class="views-row">([\s\S]*?)</div>\s*</div>')
SSYLKA = re.compile(r'href="(/fond/[^"]+)"')
ZAGOL = re.compile(r'views-field-field-zagolovok[^>]*>\s*<span[^>]*>([\s\S]*?)</span>')
TAGS = re.compile(r"<[^>]+>")

# ⭐ Масштаб прямо в заголовке, в трёх формах сразу
MASSHTAB = re.compile(
    r"масштаб[^.;]{0,60}?(?:1\s*(?:дюйм|д\.)\s*=\s*[\d.,]+\s*(?:верст|саж)\w*"
    r"|1\s*(?:мм|см)\s*=\s*[\d.,]+\s*(?:верст|саж)\w*"
    r"|1\s*:\s*[\d\s]{3,12}"
    r"|[\d.,]+\s*(?:верст|саж)\w*\s*в\s*(?:дюйм|д\.)\w*)", re.I)
BEZ_MASSHTABA = re.compile(r"без\s+масштаба", re.I)
FORMAT = re.compile(r"формат[^.;]{0,30}?(\d{2,4}\s*[хx×]\s*\d{2,4})", re.I)
TEHNIKA = re.compile(r"\b(рукописн\w+|печатн\w+|литографи\w+|гравирован\w+|фотокопи\w+"
                     r"|копи\w+|калька|синька|в\s+красках|чертеж\w*)", re.I)

# Запросы: 4 губернии и уезды + темы фондов 33 и 19
ZAPROSY = [
    "Калужской", "Калужская", "Смоленской", "Смоленская", "Ярославской", "Ярославская",
    "Пермской", "Пермская", "Боровск", "Козельск", "Медынь", "Мосальск", "Таруса",
    "Жиздра", "Мещовск", "Перемышль", "Лихвин", "Малоярославец",
    "Вязьма", "Гжатск", "Дорогобуж", "Духовщина", "Поречье", "Рославль", "Юхнов",
    "Ельня", "Сычевка", "Углич", "Мышкин", "Пошехонье", "Молога", "Рыбинск",
    "Романов-Борисоглебск", "Соликамск", "Чердынь", "Кунгур", "Оханск", "Верхотурье",
    "Ирбит", "Шадринск", "Красноуфимск", "Камышлов", "Екатеринбург",
    # корабельные леса и лесное хозяйство (фонды 33, 19)
    "корабельных лесов", "корабельные леса", "лашман", "лесопильн", "корабельных рощ",
    "дубовые рощи", "порубка леса", "лесная дача", "Низового округа",
]


def chistit(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAGS.sub(" ", s))).strip()


def razobrat_shifr(put: str) -> dict:
    """Фонд, опись, единица хранения — прямо из адреса карточки."""
    m = re.search(r"/fond/([^/]+)/fond-[^/]+-opis-([^/]+)/[^/]*edkhr(\d+)", put, re.I)
    if m:
        return {"fond": m.group(1).upper(), "opis": m.group(2), "ed_hr": m.group(3)}
    m = re.search(r"/fond/([^/]+)/fond-[^/]+-opis-([^/]+)", put, re.I)
    if m:
        return {"fond": m.group(1).upper(), "opis": m.group(2), "ed_hr": ""}
    return {"fond": "", "opis": "", "ed_hr": ""}


def iskat(s: requests.Session, zapros: str, page: int,
          cherez_jina: bool = False, tolko_pryamo: bool = False) -> str | None:
    """Страница выдачи. Сначала напрямую, при неудаче — через Jina."""
    url = f"{BASE}?search_api_fulltext={requests.utils.quote(zapros)}"
    if page:
        url += f"&page={page}"

    if not cherez_jina:
        for n in range(2):
            try:
                r = s.get(url, timeout=45)
                if r.ok:
                    return r.text
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2 + 3 * n)
        if tolko_pryamo:
            return None

    # ⚠️ без X-Return-Format: html Jina отдаёт markdown БЕЗ ССЫЛОК,
    # а шифр единицы хранения читается именно из адреса карточки
    for n in range(3):
        try:
            r = s.get(JINA + url, headers={"X-Return-Format": "html"}, timeout=120)
            if r.ok and STRANICA_POISKA in r.text:
                return r.text
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5 + 5 * n)

    # ⚠️ ТРЕТЬЯ СТУПЕНЬ. Часть запросов Jina отбивает намертво: «Екатеринбург»,
    # «лашман» и ещё 20 стабильно дают 422 «Timeout was reached» за 4 секунды,
    # тогда как «Молога» через неё проходит. Ни X-Timeout, ни X-No-Cache, ни
    # смена URL не помогают — отказ не кэш и не объём выдачи.
    # ⚠️ ОПАСНО: такой отказ выглядит как ПУСТАЯ выдача. В прогоне 24.10 он
    # дал 22 запроса подряд с «0 записей», и «Екатеринбург» среди них — а на
    # деле там 2 единицы хранения. Поэтому отказ обязан отличаться от пустоты:
    # функция возвращает None (не пустую строку), и вызывающий код не пишет
    # «КОНЕЦ» в журнал, оставляя запрос на следующий заход.
    return cherez_scrapedo(s, url)


def cherez_scrapedo(s: requests.Session, url: str) -> str | None:
    """Последняя ступень цепочки: платный прокси с собственным пулом адресов."""
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return None
    if not token:
        return None
    for n in range(2):
        try:
            r = s.get(SCRAPEDO, params={"token": token, "url": url}, timeout=120)
            if r.ok and STRANICA_POISKA in r.text:
                return r.text
        except Exception:  # noqa: BLE001
            pass
        time.sleep(4 + 4 * n)
    return None


def razobrat(doc: str, zapros: str) -> list[dict]:
    out = []
    for blok in ROW.findall(doc):
        m = SSYLKA.search(blok)
        if not m:
            continue
        put = m.group(1)
        zag = chistit((ZAGOL.search(blok) or [None, ""])[1])
        if not zag:
            continue
        mm = MASSHTAB.search(zag)
        gody = re.findall(r"\b(1[5-9]\d{2}|19[0-4]\d)\b", zag)
        teh = [t.lower() for t in TEHNIKA.findall(zag)]
        out.append({
            **razobrat_shifr(put),
            "shifr": f"Ф. {razobrat_shifr(put)['fond']} оп. {razobrat_shifr(put)['opis']} "
                     f"д. {razobrat_shifr(put)['ed_hr']}".strip(),
            "zagolovok": zag[:600],
            # ⭐ масштаб и формат — прямо из заголовка, без распознавания скана
            "masshtab": (mm.group(0) if mm else
                         ("без масштаба" if BEZ_MASSHTABA.search(zag) else "")),
            "format_lista": (FORMAT.search(zag) or [None, ""])[1],
            "tehnika": "; ".join(dict.fromkeys(teh))[:120],
            "god": gody[0] if gody else "",
            "url": "https://rgavmf.ru" + put,
            "zapros": zapros,
            "istochnik": "РГАВМФ (Российский государственный архив Военно-Морского Флота)",
        })
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="сколько запросов взять")
    ap.add_argument("--jina", action="store_true", help="только через прокси Jina")
    ap.add_argument("--pryamo", action="store_true", help="только напрямую")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if DST.exists():
        for ln in DST.open(encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                done.add(json.loads(ln)["url"])
            except Exception:  # noqa: BLE001, S112
                continue
    proideno: set[str] = set()
    if SHAGI.exists():
        proideno = {x for x in SHAGI.read_text(encoding="utf-8").splitlines() if x}

    zaprosy = ZAPROSY[: args.limit] if args.limit else ZAPROSY
    print(f"запросов {len(zaprosy)}, собрано {len(done)}, шагов пройдено {len(proideno)}",
          flush=True)

    s = requests.Session()
    s.headers["User-Agent"] = UA
    novyh = 0
    nedostup: list[str] = []
    shlog = SHAGI.open("a", encoding="utf-8")
    with DST.open("a", encoding="utf-8") as fh:
        for i, q in enumerate(zaprosy, 1):
            if f"{q}|КОНЕЦ" in proideno:
                print(f"  {i:>3}/{len(zaprosy)} «{q[:34]}» — пройден ранее", flush=True)
                continue
            vsego = 0
            for page in range(MAX_STRANIC):
                if f"{q}|{page}" in proideno:
                    continue
                doc = iskat(s, q, page, cherez_jina=args.jina,
                            tolko_pryamo=args.pryamo)
                if not doc:
                    # не достучались — это НЕ пустая выдача; «КОНЕЦ» не пишем,
                    # запрос останется на следующий заход
                    nedostup.append(q)
                    break
                zapisi = razobrat(doc, q)
                if not zapisi:
                    shlog.write(f"{q}|КОНЕЦ" + "\n")
                    shlog.flush()
                    break
                for r in zapisi:
                    if r["url"] in done:
                        continue
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    done.add(r["url"])
                    novyh += 1
                fh.flush()
                shlog.write(f"{q}|{page}" + "\n")
                shlog.flush()
                vsego += len(zapisi)
                time.sleep(DELAY if args.pryamo else DELAY_JINA)
                if len(zapisi) < 100:
                    shlog.write(f"{q}|КОНЕЦ" + "\n")
                    shlog.flush()
                    break
            print(f"  {i:>3}/{len(zaprosy)} «{q[:34]:36}» записей {vsego:>5}, "
                  f"всего {len(done):>6}", flush=True)
    shlog.close()

    rows = []
    for ln in DST.open(encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:  # noqa: BLE001, S112
            continue
    if rows:
        cols = sorted({k for r in rows for k in r})
        with (OUT / "rgavmf_items.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    from collections import Counter
    if nedostup:
        print(f"\n⚠️ НЕ ДОСТУЧАЛИСЬ (это не пустая выдача!), "
              f"повторить заходом: {len(nedostup)}")
        print("   " + ", ".join(dict.fromkeys(nedostup)))
    print(f"\nновых за прогон: {novyh} | всего: {len(rows)}")
    print(f"с масштабом в заголовке: {sum(1 for r in rows if r.get('masshtab'))}")
    print(f"с форматом листа:        {sum(1 for r in rows if r.get('format_lista'))}")
    print("по фондам:", dict(Counter(r["fond"] for r in rows).most_common(10)))
    print(f"→ {OUT / 'rgavmf_items.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
