"""Добор карточек НЭБ через scrape.do — обход гео-блокировки 403.

Зачем. 495 карточек НЭБ остались недобранными: rusneb.ru отдаёт 403 на программные
запросы из зарубежной сети, и Jina-прокси тоже блокируется (её IP не российский).
scrape.do с geoCode=ru проходит (проверено 08.11.2026). РГО (elib.rgo.ru) не берётся
даже так — сайт отвечает 502 через российские прокси, то есть лежит сам.

⚠️ Квота scrape.do: 1000 запросов в месяц, 5 одновременных. Перед прогоном печатается
остаток; при остатке меньше, чем нужно строк, прогон не стартует без --force.

Вход  — output/work_2026-11-08/harvested.jsonl (строки со статусом «хост недоступен»).
Выход — output/work_2026-11-08/harvested_neb.jsonl, построчно, с возобновлением по ключу.

  python harvest_neb_scrapedo.py --limit 5     # проба
  python harvest_neb_scrapedo.py               # полный прогон
"""

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"C:\Users\admin\.claude\skills\scrapedo-web-scraper\scripts")
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402
from scrape import get_token  # noqa: E402

from territory_gate import classify as terr_classify  # noqa: E402

DIR = Path(__file__).resolve().parents[1] / "output" / "work_2026-11-08"
SRC = DIR / "harvested.jsonl"
OUT = DIR / "harvested_neb.jsonl"

API = "https://api.scrape.do/"
ROW = re.compile(
    r'cards-table__left"?>\s*(.*?)\s*</div>\s*<div class="cards-table__right"?>\s*(.*?)\s*</div>',
    re.S,
)
SC = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})")
TAIL = re.compile(
    r"\s*[—-]\s*(?:читать|смотреть|скачать).*$|\s*\|\s*НЭБ.*$", re.I | re.S
)

_lock = threading.Lock()


def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "; ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return unescape(re.sub(r"\s+", " ", s)).strip(" ;")


def parse(html: str) -> dict:
    out: dict = {}
    fields = {}
    for lab, val in ROW.findall(html):
        lab, val = strip_tags(lab), strip_tags(val)
        if lab and val:
            fields.setdefault(lab, val)
    if fields:
        out["polya"] = fields

    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if m:
        t = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        t = TAIL.sub("", t).strip(" .|—-")
        t = re.sub(r"\s*\[\d{6}_\d{6}_[\w]+\]\s*$", "", t).strip()
        if t:
            out["zagolovok_polnyi"] = t

    for k in ("Масштаб", "Математическая основа", "Примечание"):
        if k in fields and (s := SC.search(fields[k])):
            out["scale"] = int(re.sub(r"\D", "", s.group(1)))
            out["scale_ctx"] = fields[k][:150]
            break
    if "scale" not in out and out.get("zagolovok_polnyi"):
        if s := SC.search(out["zagolovok_polnyi"]):
            out["scale"] = int(re.sub(r"\D", "", s.group(1)))
            out["scale_ctx"] = s.group(0)

    for k in ("Шифр хранения", "Шифр", "Шифр хранения оригинала"):
        if k in fields:
            out["shelf"] = fields[k]
            break
    for k in ("Библиотека", "Место хранения оригинала", "Фондодержатель"):
        if k in fields:
            out["hranitel"] = fields[k]
            break
    if "Год" in fields or "Год издания" in fields:
        out["god_text"] = fields.get("Год") or fields.get("Год издания")
    return out


def fetch(token: str, url: str, tries: int = 6) -> str | None:
    """Ответ scrape.do с отступом на 429.

    ⚠️ Грабли 08.11.2026: при 5 воркерах тариф отдаёт 429 «You are sending too fast»
    примерно на 40 % запросов — слоты съедает сам прогон. 429 НЕ списывает квоту,
    но ломает строку. Поэтому воркеров 2 и экспоненциальный отступ на 429.
    """
    delay = 4.0
    for _ in range(tries):
        try:
            r = requests.get(
                API, params={"token": token, "url": url, "geoCode": "ru"}, timeout=120
            )
            if r.status_code == 200 and "Отключите VPN" not in r.text:
                return r.text
            if r.status_code == 429:
                time.sleep(delay)
                delay = min(delay * 1.7, 40)
                continue
            if r.status_code in (404, 410):
                return None
        except requests.RequestException:
            time.sleep(delay)
    return None


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    # ⚠️ ЗАМОК. Инцидент 08.11.2026: фоновые прогоны убивались системой по памяти,
    # обёртка умирала, а сам python продолжал работать — и следующий запуск шёл
    # ВТОРЫМ процессом. Три одновременных прогона съели все 5 слотов scrape.do,
    # дали лавину 429 и дубли строк. Теперь второй экземпляр просто не стартует.
    lock = DIR / "harvest_neb.lock"
    if lock.exists():
        age = time.time() - lock.stat().st_mtime
        if age < 1800:
            sys.exit(
                f"прогон уже идёт (замок {lock.name}, обновлён {age:.0f} с назад). "
                "Если процесс точно мёртв — удалить файл замка."
            )
        print(f"замок устарел ({age / 60:.0f} мин) — перехватываю")
    lock.write_text(str(time.time()), encoding="utf-8")

    token = get_token()
    if not token:
        lock.unlink(missing_ok=True)
        sys.exit("нет токена scrape.do")

    info = requests.get("https://api.scrape.do/info", params={"token": token}, timeout=30).json()
    left = info.get("RemainingMonthlyRequest", 0)
    print(f"остаток запросов scrape.do: {left}")

    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8") if ln.strip()]
    todo = [
        r
        for r in rows
        if r.get("status") != "добрано" and "rusneb.ru" in (r.get("url") or "")
    ]
    done = set()
    if OUT.exists():
        done = {
            json.loads(ln)["key"]
            for ln in OUT.open(encoding="utf-8")
            if ln.strip() and json.loads(ln).get("status") == "добрано"
        }
    todo = [r for r in todo if r["key"] not in done]

    # ПОРЯДОК ДОБОРА ПО ПОЛЬЗЕ. Прогон рвётся по памяти машины, поэтому важное
    # должно попасть в файл первым, а бесполезное — не тратить квоту вовсе:
    #   1) «наша» по короткому заголовку — прямые кандидаты в каталог;
    #   2) «нет» — решение требует карточки, без неё запись подвешена;
    #   х) «чужая»/«общая» — территория уже ясна из заголовка, карточка ничего
    #      не изменит: пропускаем и пишем причину (это решение, не потеря).
    order = {"наша": 0, "нет": 1}
    skipped = []
    ranked = []
    for r in todo:
        verdict = terr_classify(r.get("zagolovok") or "")[0]
        if verdict in order:
            ranked.append((order[verdict], r))
        else:
            r["_skip"] = verdict
            skipped.append(r)
    ranked.sort(key=lambda x: x[0])
    todo = [r for _, r in ranked]
    if skipped:
        with OUT.open("a", encoding="utf-8") as fh:
            for r in skipped:
                fh.write(
                    json.dumps(
                        {
                            "key": r["key"],
                            "url": r["url"],
                            "seriya": r.get("seriya"),
                            "zagolovok": r.get("zagolovok"),
                            "status": "не добирался",
                            "prichina": (
                                f"территория ясна из заголовка ({r['_skip']}) — "
                                "карточка решения не изменит, квота не тратится"
                            ),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        print(f"пропущено без запроса (чужая/общая по заголовку): {len(skipped)}")

    if args.limit:
        todo = todo[: args.limit]
    print(f"к добору: {len(todo)} (уже добрано ранее: {len(done)})")
    if not todo:
        return
    if len(todo) > left and not args.force:
        sys.exit(f"нужно {len(todo)} запросов, остаток {left} — прогон отменён (--force чтобы всё равно)")

    fh = OUT.open("a", encoding="utf-8")
    ok = fail = 0

    def work(row: dict) -> None:
        nonlocal ok, fail
        body = fetch(token, row["url"])
        rec = {k: row.get(k) for k in ("key", "url", "seriya", "zagolovok", "istochnik")}
        if body:
            rec.update(parse(body))
            rec["status"] = "добрано"
            rec["istochnik_kartochki"] = "scrape.do geoCode=ru"
        else:
            rec["status"] = "не ответил (scrape.do)"
        with _lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            lock.write_text(str(time.time()), encoding="utf-8")  # замок живой
            if rec["status"] == "добрано":
                ok += 1
            else:
                fail += 1
            n = ok + fail
            if n % 10 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} | добрано {ok}, не ответил {fail}", flush=True)

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            list(ex.map(work, todo))
    finally:
        fh.close()
        lock.unlink(missing_ok=True)
    print(f"готово: добрано {ok}, не ответил {fail} → {OUT.name}")


if __name__ == "__main__":
    main()
