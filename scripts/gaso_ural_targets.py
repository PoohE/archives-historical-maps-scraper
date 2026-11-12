"""ГАСО-Урал: разрешить номера целевых фондов в id портала и снять состав описей.

Позиции А28–А32 реестра — фонды Государственного архива Свердловской области,
в наши прогоны не входившие. Две находки 09.11.2026, определившие устройство скрипта:

  1) **номер фонда НЕ равен id в URL.** `/show/funds/59/` отдаёт ф. 64; проверено
     поиском: «фонд номер:59» → id 56, «фонд номер:64» → id 59, «фонд номер:773» → id 625.
     Поэтому id разрешаются через `/show/search/?q=фонд номер:<N>`, а не угадываются.
  2) **постраничный список `/show/funds/pages/N` непригоден** — каждая страница
     отдаёт почти один и тот же набор ссылок (100 ссылок, 1 новая), то есть это
     боковой блок, а не страница списка. Обход по номерам через поиск надёжнее.

Портал публикует **сканы описей**, а не записи дел, поэтому объём работы здесь
измеряется числом сканов под распознавание.

  python gaso_ural_targets.py
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

BASE = "https://opisi.gaso-ural.ru"
OUT = Path(__file__).resolve().parents[1] / "output" / "gaso_ural"
UA = {
    "User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)",
    "Accept-Language": "ru,en;q=0.8",
}
DELAY = 1.2

#: номер фонда → зачем он нам (позиция реестра)
TARGETS = {
    "59": "А28 Чертёжная Уральского горного правления, >30 тыс. ед. хр.",
    "64": "А29 коллекция топографических съёмок Бержье, Аллори и КВТ 1854–1865, 409 дел",
    "773": "А13/А30 карты лесных дач Камышловского уезда, 128 ед. хр., 1826–1916",
    "24": "А31 Уральское горное управление",
    "55": "А31 Лесное отделение Уральского горного управления",
    "9": "А31 Билимбаевский горный округ Строганова",
    "14": "А31 заводоуправление Сергинско-Уфалейского округа",
    "45": "А31 управление Богословским горным округом",
    "148": "А31 правление Лысьвенского горного округа Шуваловых",
    "160": "А31 управление заводами Гороблагодатского округа",
    "374": "А25 Красноуфимская уездная землеустроительная комиссия",
    "713": "А25 Ирбитская уездная землеустроительная комиссия, 10 дел",
    "761": "А25 Верхотурская уездная землеустроительная комиссия, 2 дела",
}


def fetch(url: str) -> str | None:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=45
        ) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def text_of(html: str) -> str:
    body = html
    for tag in ("script", "style"):
        body = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", body, flags=re.S | re.I)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", body)))


def resolve(num: str) -> list[str]:
    """id фондов, найденные поиском по строгому номеру."""
    q = urllib.parse.quote(f"фонд номер:{num}")
    html = fetch(f"{BASE}/show/search/?q={q}")
    if not html:
        return []
    return sorted(set(re.findall(r"/show/funds/(\d+)/", html)))


def parse_fund(html: str) -> dict:
    t = text_of(html)
    out: dict = {}
    m = re.search(r"Фонд\s*№\s*([\w\-./]+)\s+(.{3,220}?)\s+Описи фонда", t)
    if m:
        out["fund"] = m.group(1).strip()
        out["name"] = m.group(2).strip()
    seg = t.split("Описи фонда:", 1)[1] if "Описи фонда:" in t else ""
    seg = seg.split("Описи дел фондов ГАСО", 1)[0]
    pairs = re.findall(r"([\w\-./]+)\s+(\d+)\s+скан", seg)
    if pairs:
        out["opisi"] = [{"opis": a, "scans": int(b)} for a, b in pairs]
        out["scans_total"] = sum(int(b) for _, b in pairs)
    out["list_ids"] = sorted(set(re.findall(r"/show/lists/(\d+)/", html)))
    return out


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    res: dict[str, dict] = {}
    for num, why in TARGETS.items():
        ids = resolve(num)
        time.sleep(DELAY)
        rec: dict = {"why": why, "ids": ids}
        for fid in ids:
            html = fetch(f"{BASE}/show/funds/{fid}/")
            time.sleep(DELAY)
            if not html:
                continue
            p = parse_fund(html)
            got = (p.get("fund") or "").lstrip("Рр-Фф ").strip()
            if got == num:
                rec.update(p)
                rec["id"] = fid
                rec["url"] = f"{BASE}/show/funds/{fid}/"
                break
            rec.setdefault("otherwise", []).append({"id": fid, "fund": p.get("fund")})
        res[num] = rec
        mark = "✅" if rec.get("id") else "⛔"
        name = (rec.get("name") or "— не найден по строгому номеру —")[:62]
        print(f"  {mark} ф. {num:>4s} id={rec.get('id') or '?':>4} "
              f"описей {len(rec.get('opisi') or []):>3} сканов "
              f"{rec.get('scans_total') or 0:>5} | {name}", flush=True)

    p = OUT / "target_funds.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [k for k, v in res.items() if v.get("id")]
    tot = sum(v.get("scans_total") or 0 for v in res.values())
    print(f"\nнайдено {len(ok)} из {len(TARGETS)}; сканов описей суммарно: {tot}")
    miss = [k for k in TARGETS if k not in ok]
    if miss:
        print("  не разрешились: " + ", ".join(miss))
    print(f"→ {p}")


if __name__ == "__main__":
    main()
