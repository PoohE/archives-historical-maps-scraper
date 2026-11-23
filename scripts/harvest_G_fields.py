# -*- coding: utf-8 -*-
"""Добор полей по карточкам улова «наши губернии»: полное название, год, шифр, выходные данные.

Зачем. Улов серийного прогона несёт только обрезанный заголовок и ссылку, а чек-лист
предзаливки требует восемнадцати полей. Без добора карточки в каталог пускать нельзя.

Вход  — `output/triage_G/наша.jsonl` (и `межгуб.jsonl` по флагу).
Выход — `output/triage_G/harvested.jsonl`, построчно, с возобновлением по URL.

Маршруты и вежливость: ходим только на библиотечные карточки, по одной, с паузой на хост.
НЭБ держим на 4 с — на 1,5 с он троттлит (установлено 14.11: 424 отказа из 493 при паузе 1,5 с
и ноль отказов при 4 с).

  python harvest_G_fields.py --limit 5     # проба
  python harvest_G_fields.py               # полный прогон
  python harvest_G_fields.py --mezh        # добор по межгубернским
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import fix_stdout, log  # noqa: E402

# ⚠️ `common.log` — ФАБРИКА логгеров, а не print: вызов log("текст") создавал
# логгер с таким именем и не печатал ничего. Из-за этого прогон добора полей
# 15.11.2026 отработал 71 минуту с ПУСТЫМ логом — следить было не за чем.
LOG = log("harvest_G_fields")

DIR = Path(__file__).resolve().parents[1] / "output" / "triage_G"
# Контакт в User-Agent — из переменной среды CRAWL_CONTACT (как в harvest_cards.py):
# личную почту в коде публичного репозитория не держим.
_CONTACT = os.environ.get("CRAWL_CONTACT", "").strip()
UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347"
                    + (f"; contact {_CONTACT}" if _CONTACT else "") + ")",
      "Accept-Language": "ru-RU,ru;q=0.9"}
DELAY = {"rusneb.ru": 4.0, "kp.rusneb.ru": 4.0, "search.rsl.ru": 1.2, "www.prlib.ru": 2.0,
         "elib.rgo.ru": 2.5, "elib.shpl.ru": 2.0, "catalog.shpl.ru": 2.0,
         "elib.smolensklib.ru": 2.0, "lib.permkrai.ru": 2.0, "elib.uraic.ru": 2.0}
DEAD_AFTER = 3

_last: dict[str, float] = {}
_fails: dict[str, int] = {}

YEAR = re.compile(r"\b(1[5-9]\d{2}|19[0-2]\d)\b")
SCALE = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})|(\d+)\s*(?:вёрст|верст|саж)\w*\s+в\s+дюйм")
SHELF = re.compile(r"((?:FB|KGR|OMF|IZO|MK|ZV|NTO|Кс|К)\s?[\d\w/\-.№ ]{3,28}?)\s*(?:\||$|Читать|Заказать)")
TAILS = (" - Search RSL", " | НЭБ", " | Президентская библиотека имени Б.Н. Ельцина",
         " | НЭБ Книжные памятники", " — читать книгу онлайн, скачать бесплатно PDF",
         " | Президентская библиотека")


def card_url(url: str) -> str:
    """Привести ссылку улова к ссылке КАРТОЧКИ.

    ⚠️ 15.11.2026: 8 из 14 недоборов оказались не карточками, а прямыми ссылками на файл
    `lib.permkrai.ru/node/<id>/pdfbook/download/<имя>.pdf` — парсер искал поля в PDF и честно
    возвращал «карточка пуста». Поля лежат на `node/<id>`, его и запрашиваем.
    """
    m = re.match(r"(https?://lib\.permkrai\.ru/node/\d+)/pdfbook/download/", url)
    return m.group(1) if m else url


def fetch(url: str) -> str | None:
    host = url.split("/")[2]
    if _fails.get(host, 0) >= DEAD_AFTER:
        return None
    gap = DELAY.get(host, 2.0)
    wait = gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            _fails[host] = 0
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        _fails[host] = _fails.get(host, 0) + 1
        return None


def parse(html: str) -> dict:
    t = re.search(r"<title>(.*?)</title>", html, re.S)
    title = re.sub(r"\s+", " ", t.group(1)).replace("&quot;", '"').strip() if t else ""
    for tail in TAILS:
        title = title.replace(tail, "")
    years = YEAR.findall(title)
    sc = SCALE.search(title)
    sh = SHELF.search(title)
    return {
        "полное_название": title.strip(" .|"),
        "год_нижний": years[0] if years else None,
        "год_верхний": years[-1] if len(years) > 1 else None,
        "масштаб_из_заголовка": (sc.group(0).strip() if sc else None),
        "шифр_из_заголовка": (sh.group(1).strip() if sh else None),
    }


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mezh", action="store_true", help="добирать межгубернские")
    ap.add_argument("--retry", action="store_true",
                    help="перебрать записи со статусом «не ответил»/«карточка пуста»")
    args = ap.parse_args()

    src = DIR / ("межгуб.jsonl" if args.mezh else "наша.jsonl")
    if not src.exists():
        sys.exit(f"нет входа: {src} — сначала triage_G_hits.py")
    rows = [json.loads(x) for x in src.open(encoding="utf-8") if x.strip()]

    out_path = DIR / ("harvested_mezh.jsonl" if args.mezh else "harvested.jsonl")
    done = set()
    prev: dict[str, dict] = {}
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                r0 = json.loads(line)
                done.add(r0["url"])
                prev[r0["url"]] = r0
            except (json.JSONDecodeError, KeyError):
                continue
    if args.retry:
        # Перебор неудач. Хост мог не ответить разово (у НЭБ и РГБ так и было), а «карточка
        # пуста» иногда означает иную вёрстку страницы, а не отсутствие данных. Удачные
        # строки сохраняем как есть, файл перезаписываем — иначе в нём будет две версии
        # одной записи и дальше не понять, какая свежая. Копия на всякий случай рядом.
        bad = [u for u, r0 in prev.items() if r0.get("статус") != "добрано"]
        LOG.info(f"перебор неудач: {len(bad)} из {len(prev)} добранных ранее")
        if bad:
            backup = out_path.with_suffix(".jsonl.bak")
            backup.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
            with out_path.open("w", encoding="utf-8") as f:
                for u, r0 in prev.items():
                    if r0.get("статус") == "добрано":
                        f.write(json.dumps(r0, ensure_ascii=False) + chr(10))
        todo = [prev[u] for u in bad]
    else:
        todo = [r for r in rows if r["url"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    LOG.info(f"всего карточек: {len(rows)} | уже добрано: {len(done)} | к обходу: {len(todo)}")

    got = empty = failed = 0
    with out_path.open("a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            html = fetch(card_url(r["url"]))
            if html is None:
                r["статус"] = "не ответил"
                failed += 1
            else:
                fields = parse(html)
                r.update(fields)
                if fields["полное_название"]:
                    r["статус"] = "добрано"
                    got += 1
                else:
                    r["статус"] = "карточка пуста"
                    empty += 1
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if i % 25 == 0:
                LOG.info(f"  {i}/{len(todo)} — добрано {got}, пусто {empty}, не ответил {failed}")

    LOG.info(f"готово: добрано {got}, пусто {empty}, не ответил {failed} → {out_path}")


if __name__ == "__main__":
    main()
