"""Проба: публикует ли держатель шифр хранения в карточке источника.

Зачем. Правило каталога: у записи обязателен архивный или библиотечный шифр — без него
источник нельзя заказать в читальном зале, и запись бесполезна. В улове 13–16.11 шифр
не запрашивался у библиотек, а вытягивался из текста заголовка, и дал название вместо
шифра. Прежде чем строить добор, надо знать по каждому держателю: шифр в карточке есть
или его там нет вовсе.

Проба берёт по одной-две карточки на держателя, читает страницу и ищет подписи полей
(«Шифр», «Шифр хранения», «Инвентарный номер», «Место хранения», «Номер единицы
хранения»). Вывод — что нашлось рядом с подписью, чтобы решение принималось по
фактическому тексту карточки, а не по памяти о том, как устроен сайт.

Цепочка доступа — по правилу web-access: прямой запрос, при неудаче Jina-прокси.

  python scripts/probe_shelf_marks.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "shelf_probe_2026-11-22"

PROBE = {
    "ПГКБ (Пермская краевая)": ["https://lib.permkrai.ru/node/2371"],
    "НЭБ": ["https://rusneb.ru/catalog/000199_000009_008730959/"],
    "РГБ": ["https://search.rsl.ru/ru/record/01008730959"],
    "ПрБ (Президентская)": ["https://www.prlib.ru/item/757189"],
    "РНБ-Вивальди": ["https://vivaldi.nlr.ru/cm000010312/details"],
    "ГПИБ": ["http://elib.shpl.ru/ru/nodes/16157"],
    "РГО (Картфонд)": ["https://elib.rgo.ru/handle/123456789/227869"],
}

# подписи полей, за которыми в карточке идёт шифр
LABELS = [
    "шифр хранения", "шифр", "инвентарный номер", "инв. номер", "инв.номер",
    "номер единицы хранения", "единица хранения", "место хранения",
    "хранение", "call number", "shelf", "классификац",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TAGS = re.compile(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", re.S | re.I)


def fetch(url: str) -> tuple[str, str]:
    """(текст, каким путём добыт). Прямой запрос, затем Jina-прокси."""
    for how, target in (("прямой", url), ("jina", "https://r.jina.ai/" + url)):
        try:
            req = urllib.request.Request(target, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru,en;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
            for enc in ("utf-8", "cp1251"):
                try:
                    return raw.decode(enc), how
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "replace"), how
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
            continue
    return "", f"не добыто ({last})"


def plain(html: str) -> str:
    t = TAGS.sub(" ", html)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&nbsp;", " ").replace("&mdash;", "—")
          .replace("&laquo;", "«").replace("&raquo;", "»").replace("&amp;", "&"))
    return re.sub(r"[ \t ]+", " ", t)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for holder, urls in PROBE.items():
        print(f"\n{'=' * 70}\n{holder}")
        for url in urls:
            html, how = fetch(url)
            print(f"  {url}\n  путь: {how} | знаков: {len(html)}")
            if not html:
                report[holder] = {"url": url, "how": how, "hits": []}
                continue
            (OUT / (re.sub(r"\W+", "_", holder)[:40] + ".txt")).write_text(
                plain(html), encoding="utf-8")
            text = plain(html)
            low = text.lower()
            hits = []
            for lab in LABELS:
                for m in re.finditer(re.escape(lab), low):
                    frag = text[m.start():m.start() + 160].strip()
                    frag = re.sub(r"\s+", " ", frag)
                    if frag not in hits:
                        hits.append(frag)
                    if len(hits) >= 12:
                        break
                if len(hits) >= 12:
                    break
            if hits:
                print("  НАЙДЕНЫ подписи полей:")
                for h in hits[:8]:
                    print(f"     • {h[:150]}")
            else:
                print("  подписей шифра в карточке НЕ НАЙДЕНО")
            report[holder] = {"url": url, "how": how, "hits": hits}
            time.sleep(2)
    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
