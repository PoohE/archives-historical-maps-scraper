"""Президентская библиотека: переоткрытие — слой описаний и статистики.

⚠️ Почему источник ПЕРЕОТКРЫТ. 09.10 по ПБ закрыли МАРШРУТ публичных региональных
коллекций (7 из 7, 531 карточка → 451 → 43 в каталог). Маршрут закрыт верно, но это
не фонд библиотеки: 21.10 пользователь прислал `prlib.ru/item/1618094` —
«Статистическое описание Калужской губернии. Т. 6. Мещовский уезд. Вып. 1» (Калуга,
тип. губ. земства, 1912; скан ПБ, оригинал в ГПИБ). Проверка: в наших наборах ПБ
этого издания НЕТ ВООБЩЕ — ни по номеру, ни по названию. Причина та же, что у ГПИБ:
шли картографическими разделами и предметными рубриками, а земско-статистический
слой мимо них проходит.

Маршрут. `robots.txt` ПБ запрещает поиск (`/search`, `/en/search`, `/prlib_sug`,
`/prlib_search`, `/?q=search/`), но карточки `/item/<id>` открыты; адресных запретов
ИИ-агентам нет (из агентов запрещён только AhrefsBot). `Crawl-delay: 2` — соблюдаем.
`sitemap.xml` бесполезен: в нём 15 верхних страниц, карточек нет. Значит ищем внешним
поисковиком (site:prlib.ru через Яндекс), читаем разрешённые карточки.

Две фазы:
    sweep — запросы в Яндекс, сбор номеров карточек;
    cards — чтение карточек /item/<id>: описание, выходные данные, хранение оригинала.

Запуск:
    python -B scripts_prlib/prlib_yandex_sweep.py --phase sweep --limit 4
    python -B scripts_prlib/prlib_yandex_sweep.py --phase all
"""
from __future__ import annotations

import argparse
import csv
import html as H
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "prlib_opisaniya_20261021"
SKILL = Path.home() / ".claude" / "skills" / "yandex-search-api"
# ⚠️ голый «bash» на Windows уходит в WSL и молча не отрабатывает — только Git Bash
BASH = next((p for p in (r"C:\Program Files\Git\bin\bash.exe",
                         r"C:\Program Files\Git\usr\bin\bash.exe")
             if Path(p).exists()), "bash")
HOST = "https://www.prlib.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CRAWL_DELAY = 2.0  # robots.txt ПБ

GUBERNII = ["Калужской", "Смоленской", "Ярославской", "Пермской"]
KINDS = [
    "статистическое описание {g} губернии",
    "список населенных мест {g} губернии",
    "памятная книжка {g} губернии",
    "материалы для географии и статистики {g} губернии",
    "военно-статистическое обозрение {g} губернии",
    "топографическое описание {g} губернии",
    "оценочно-статистическое описание {g} губернии",
    "карта {g} губернии",
    "атлас {g} губернии",
    "планы генерального межевания {g} губернии",
]
ITEM = re.compile(r"prlib\.ru/item/(\d+)")
GUB_RE = re.compile(r"Калужск|Смоленск|Ярославск|Пермск", re.I)

FIELDS = ["Издательство", "Год", "Место издания", "Коллекции", "Автор",
          "Тематика", "Тип материала", "Язык", "Объем"]


def queries() -> list[str]:
    return [f"site:prlib.ru {k.format(g=g)}" for g in GUBERNII for k in KINDS]


def run_query(q: str, results: int = 50) -> list[dict]:
    cmd = [BASH, "scripts/web_search_sync.sh", "--query", q,
           "--region-id", "225", "--results", str(results)]
    try:
        r = subprocess.run(cmd, cwd=SKILL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:  # noqa: BLE001
        print(f"    запрос не выполнен: {type(e).__name__}")
        return []
    m = re.search(r"JSON:\s*(\S+\.json)", r.stdout or "")
    if not m or not Path(m.group(1)).exists():
        return []
    try:
        return json.loads(Path(m.group(1)).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def phase_sweep(limit: int, delay: float) -> int:
    dst = OUT / "prlib_cards.jsonl"
    found: dict[str, dict] = {}
    if dst.exists():
        for ln in dst.open(encoding="utf-8"):
            try:
                r = json.loads(ln)
                found[r["item_id"]] = r
            except Exception:  # noqa: BLE001, S112
                continue
    qs = queries()
    if limit:
        qs = qs[:limit]
    print(f"запросов: {len(qs)} | уже собрано: {len(found)}")
    for i, q in enumerate(qs, 1):
        new = 0
        for r in run_query(q):
            m = ITEM.search(r.get("url", ""))
            if not m or m.group(1) in found:
                continue
            found[m.group(1)] = {
                "item_id": m.group(1),
                "zagolovok": re.sub(r"\s*\|\s*Президентская библиотека.*$", "",
                                    r.get("title", "")).strip(),
                "url": f"{HOST}/item/{m.group(1)}",
                "snippet": (r.get("snippet") or "").strip()[:300],
                "zapros": q.replace("site:prlib.ru ", ""),
                "istochnik": "Президентская библиотека (поиск через Яндекс)",
            }
            new += 1
        print(f"  {i:>3}/{len(qs)} {q.replace('site:prlib.ru ','')[:54]:<56} "
              f"+{new} (всего {len(found)})", flush=True)
        time.sleep(delay)
    with dst.open("w", encoding="utf-8") as fh:
        for r in sorted(found.values(), key=lambda x: int(x["item_id"])):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nуникальных карточек: {len(found)}")
    return len(found)


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
        time.sleep(2 + 3 * n)
    return None


def parse_card(doc: str) -> dict:
    title = ""
    m = re.search(r"<title>(.*?)</title>", doc, re.S)
    if m:
        title = re.sub(r"\s*\|\s*Президентская библиотека.*$", "",
                       re.sub(r"\s+", " ", H.unescape(m.group(1)))).strip()
    b = re.sub(r"<script.*?</script>|<style.*?</style>", "", doc, flags=re.S)
    b = re.sub(r"<[^>]+>", "\n", b)
    lines, prev = [], None
    for x in H.unescape(b).splitlines():
        x = x.strip()
        if x and x != prev and len(x) > 1:
            lines.append(x)
        prev = x
    # Блок описания: между «Описание» и «Карта сайта» (подвал)
    opis = ""
    if "Описание" in lines:
        k = lines.index("Описание")
        end = next((j for j, x in enumerate(lines[k:], k) if x == "Карта сайта"), k + 30)
        opis = " ".join(lines[k + 1:end])[:1500]
    rec = {}
    for i, line in enumerate(lines):
        if line in FIELDS and i + 1 < len(lines):
            rec.setdefault(line, lines[i + 1][:300])
    hranenie = ""
    mm = re.search(r"Место хранения оригинала:\s*([^\n]{2,200})", opis)
    if mm:
        # ⚠️ Значение не отделено от соседних блоков: после названия хранилища
        # сразу идут «Издательство», «Объект в каталогах», «В коллекциях» и т. п.
        # Обрезаем по первому такому маркеру, иначе в шифр попадёт полстраницы.
        hranenie = re.split(
            r"\s+(?:Издательство|Объект в каталогах|В коллекциях|Коллекц|\[Т|Источник)",
            mm.group(1).strip())[0].strip(" .,;")
    only_reading_room = "Доступно только в Электронных читальных залах" in "\n".join(lines)
    god = ""
    mg = re.search(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", opis or title)
    if mg:
        god = mg.group(1)
    return {
        "zagolovok": title,
        "opisanie": opis,
        "god": rec.get("Год", god),
        "izdatel": rec.get("Издательство", ""),
        "mesto": rec.get("Место издания", ""),
        "tip": rec.get("Тип материала", ""),
        "kollekcii": rec.get("Коллекции", ""),
        "hranenie_originala": hranenie,
        "tolko_chitalnyy_zal": "да" if only_reading_room else "",
    }


def phase_cards(limit: int, delay: float) -> int:
    src = OUT / "prlib_cards.jsonl"
    dst = OUT / "prlib_items.jsonl"
    seeds = [json.loads(ln) for ln in src.open(encoding="utf-8")]
    done: set[str] = set()
    if dst.exists():
        for ln in dst.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["item_id"])
            except Exception:  # noqa: BLE001, S112
                continue
    todo = [r for r in seeds if r["item_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"карточек всего {len(seeds)}, прочитано {len(done)}, в работе {len(todo)}")
    mine = 0
    with dst.open("a", encoding="utf-8") as fh:
        for i, it in enumerate(todo, 1):
            doc = get(it["url"])
            if doc is None:
                print(f"  {i:>4} {it['item_id']:>8} — не открылась", flush=True)
                time.sleep(delay)
                continue
            card = parse_card(doc)
            rec = {"item_id": it["item_id"], "url": it["url"],
                   "zapros": it.get("zapros", ""), **card,
                   "istochnik": "Президентская библиотека"}
            # ⚠️ Признак региона считать ТОЛЬКО по данным карточки. Первая версия
            # брала все значения записи, включая поле `zapros` («…Калужской
            # губернии»), и помечала нашей «Памятную книжку ОЛОНЕЦКОЙ губернии»:
            # запрос всегда содержит имя губернии, поэтому совпадало всё подряд.
            blob = " ".join(str(rec.get(k, "")) for k in
                            ("zagolovok", "opisanie", "mesto", "kollekcii"))
            rec["nash_region"] = "да" if GUB_RE.search(blob) else ""
            if rec["nash_region"]:
                mine += 1
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 20 == 0 or i <= 5 or rec["nash_region"]:
                flag = "НАШ " if rec["nash_region"] else "    "
                print(f"  {i:>4}/{len(todo)} {it['item_id']:>8} {flag}| "
                      f"{(rec['zagolovok'] or '—')[:62]}", flush=True)
            time.sleep(delay)
    rows = [json.loads(ln) for ln in dst.open(encoding="utf-8")]
    if rows:
        cols = list(rows[0])
        with (OUT / "prlib_items.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    print(f"\nпрочитано карточек: {len(rows)} | по 4 губерниям: "
          f"{sum(1 for r in rows if r.get('nash_region'))}")
    print(f"→ {OUT / 'prlib_items.csv'}")
    return len(rows)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["sweep", "cards", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.phase in ("sweep", "all"):
        print("=== ФАЗА 1: поиск через Яндекс ===")
        phase_sweep(args.limit, args.delay or 1.5)
    if args.phase in ("cards", "all"):
        print("\n=== ФАЗА 2: чтение карточек (Crawl-delay 2 с) ===")
        phase_cards(args.limit, args.delay or CRAWL_DELAY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
