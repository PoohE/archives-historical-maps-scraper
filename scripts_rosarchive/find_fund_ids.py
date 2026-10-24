"""ГИС УИАД: найти идентификаторы фондов РГВИА по их номерам.

Зачем: добор 8 фондов вне путеводителя (349 «Главное военно-техническое управление
(планы и чертежи)», 412, 369, 38, 35, 16070, личные 208 и 243) — их нашли межархивным
поиском 06.10, но идентификаторов для них в `fund_ids.json` нет: тот файл собирался
только по 17 фондам путеводителя.

Список фондов архива лежит по `/search/<архив>/?page=N`, 20 фондов на страницу, 647
страниц, упорядочены по номеру фонда. Поэтому страницу ищем расчётом (номер / 20) и
уточняем шагом в обе стороны, а не обходим все 647.

Запуск:
    python -B scripts_rosarchive/find_fund_ids.py --funds 349,412,369,38,35,208,243,16070
"""
from __future__ import annotations

import argparse
import html as H
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from cdp_fetch import Browser  # noqa: E402

ARCHIVE = "10000000001003"  # РГВИА
OUT = ROOT / "output" / "rosarchive_rgvia_20261004" / "fund_ids_extra.json"
PER_PAGE = 20

LINK = re.compile(rf'href="/search/{ARCHIVE}/(\d+)/?"[^>]*>(.*?)</a>', re.S)
FUND_NO = re.compile(r"Фонд\s+(\d+)[.\s]")


def page_funds(br: Browser, page: int) -> dict[str, tuple[str, str]]:
    url = f"https://online.archives.ru/search/{ARCHIVE}/?page={page}"
    htm = br.get(url)
    if not htm:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for fid, raw in LINK.findall(htm):
        title = re.sub(r"<[^>]+>", "", raw)
        title = re.sub(r"\s+", " ", H.unescape(title)).strip()
        m = FUND_NO.search(title)
        if m:
            out[m.group(1)] = (fid, title)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", required=True)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--span", type=int, default=4, help="сколько страниц смотреть вокруг расчётной")
    args = ap.parse_args()

    want = [x.strip() for x in args.funds.split(",") if x.strip()]
    br = Browser("https://online.archives.ru/")
    # ⚠️ накапливаем, а не перезаписываем: запуски идут порциями по нескольку фондов,
    # и перезапись стирала найденное прежде (поймано 18.10 — потерялись id 349/412/369)
    found: dict[str, tuple[str, str]] = {}
    if OUT.exists():
        found = {k: tuple(v) for k, v in json.loads(OUT.read_text(encoding="utf-8")).items()}
    seen_pages: set[int] = set()

    for num in want:
        if num in found:
            continue
        guess = max(1, (int(num) + PER_PAGE - 1) // PER_PAGE)
        for delta in range(0, args.span + 1):
            for page in {guess + delta, guess - delta}:
                if page < 1 or page in seen_pages:
                    continue
                seen_pages.add(page)
                got = page_funds(br, page)
                time.sleep(args.delay)
                found.update(got)
                if num in found:
                    break
            if num in found:
                break
        status = found[num][1][:66] if num in found else "НЕ НАЙДЕН"
        print(f"  ф.{num:>6}: {status}")

    br.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({k: list(v) for k, v in found.items()},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nнайдено идентификаторов: {len(found)} (страниц просмотрено {len(seen_pages)})")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
