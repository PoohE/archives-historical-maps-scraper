"""Госкаталог Музейного фонда РФ: поиск картографических предметов по 4 губерниям.

Разведка 20.10:
 * прямой HTTP-запрос портал отбрасывает (таймаут даже на robots) — работает ТОЛЬКО
   через браузер по CDP; прежняя запись «ConnectTimeout» была следствием этого;
 * **robots.txt отсутствует (404)** — запретов для нас нет;
 * отдельной типологии «карты» НЕТ: карты лежат внутри графики (3,9 млн), документов
   (8,4 млн) и печатной продукции (6,5 млн), поэтому обходить типологию бессмысленно —
   нужен текстовый поиск;
 * поиск кодируется прямо в адресе: `/portal/#/collections?q=<запрос>`, выдача — до 100
   карточек на странице, каждая ссылается как `collections?id=<N>`.

Названия предметов снимаем из DOM точечно (в outerHTML они перемешаны со стилями):
берём текст ссылок-карточек через querySelectorAll.

Запуск:
    python -B scripts_goskatalog/goskatalog_sweep.py --limit 3
    python -B scripts_goskatalog/goskatalog_sweep.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from cdp_fetch import Browser  # noqa: E402

OUT = ROOT / "output" / "goskatalog_20261020"
PORTAL = "https://goskatalog.ru/portal/"

GUBERNII = ["Калужской", "Смоленской", "Ярославской", "Пермской"]
KINDS = ["карта", "план", "атлас", "чертеж"]
UEZDY = {
    "Калужской": ["карта Боровского уезда", "карта Козельского уезда", "план Калуги"],
    "Смоленской": ["карта Вяземского уезда", "карта Гжатского уезда", "план Смоленска"],
    "Ярославской": ["карта Ростовского уезда", "карта Угличского уезда", "план Ярославля"],
    "Пермской": ["карта Соликамского уезда", "карта Чердынского уезда", "план Перми"],
}

# ⚠️ Название лежит НЕ в ссылке (она пустая, только картинка), а в блоке карточки
# `.catalogue__item` — первая версия собрала 1406 предметов с пустыми заголовками.
# Там же `<img src="/muzfo-imaginator/rest/images/public/...">` — это СКАН предмета,
# его обязательно забираем: у Госкаталога, в отличие от РГБ, изображения есть.
JS_CARDS = """(() => {
  const out = [];
  document.querySelectorAll('.catalogue__item').forEach(c => {
    const a = c.querySelector('a[href*="collections?id="]');
    const m = a ? (a.getAttribute('href') || '').match(/id=(\\d+)/) : null;
    if (!m) return;
    const img = c.querySelector('img');
    const src = img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
    out.push({
      id: m[1],
      title: (c.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 400),
      img: src
    });
  });
  return JSON.stringify(out);
})()"""


def queries() -> list[str]:
    out = []
    for g in GUBERNII:
        out.extend(f"{k} {g} губернии" for k in KINDS)
        out.extend(UEZDY[g])
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--wait", type=float, default=11)
    # Добор: выдача отдаёт максимум 100 карточек на запрос, а «Найдено» бывает 2219
    # («план Смоленска»). Единственный способ достать остальное — дробить запрос,
    # поэтому перечень запросов можно подать файлом (по одному в строке, # — комментарий).
    ap.add_argument("--queries-file", default="",
                    help="файл со запросами для добора (вместо встроенного набора)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.queries_file:
        qs = [ln.strip() for ln in Path(args.queries_file).read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.lstrip().startswith("#")]
    else:
        qs = queries()
    if args.limit:
        qs = qs[: args.limit]
    print(f"запросов: {len(qs)}")

    br = Browser(PORTAL)
    ws = br._conn()  # noqa: SLF001
    seq = 200

    def ev(expr: str) -> str | None:
        nonlocal seq
        seq += 1
        ws.send(json.dumps({"id": seq, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "awaitPromise": True,
                                       "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == seq:
                break
        return msg.get("result", {}).get("result", {}).get("value")

    # ⚠️ НАКОПЛЕНИЕ, не перезапись. Результат пишется через open("w"), поэтому добор
    # вторым прогоном затёр бы предметы первого (та же грабля уже стоила потерянных
    # id фондов в find_fund_ids.py). Поэтому сначала читаем уже собранное.
    found: dict[str, dict] = {}
    prev = OUT / "goskatalog_cards.jsonl"
    if prev.exists():
        for ln in prev.open(encoding="utf-8"):
            try:
                r = json.loads(ln)
                found[r["predmet_id"]] = r
            except Exception:  # noqa: BLE001, S112
                continue
        print(f"уже собрано ранее: {len(found)} предметов — добор идёт поверх")
    for i, q in enumerate(qs, 1):
        url = f"{PORTAL}#/collections?q={urllib.parse.quote(q)}"
        seq += 1
        ws.send(json.dumps({"id": seq, "method": "Page.navigate", "params": {"url": url}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == seq:
                break
        time.sleep(args.wait)
        body = ev("document.body.innerText") or ""
        total = re.search(r"Найдено\s+(\d+)", body)
        cards = json.loads(ev(JS_CARDS) or "[]")
        new = 0
        for c in cards:
            if c["id"] in found:
                continue
            img = c.get("img") or ""
            found[c["id"]] = {
                "predmet_id": c["id"],
                "zagolovok": c["title"],
                "url": f"{PORTAL}#/collections?id={c['id']}",
                # ссылка на скан предмета — то, чего не было у РГБ
                "url_skana": (f"https://goskatalog.ru{img}" if img.startswith("/") else img),
                "zapros": q,
                "istochnik": "Госкаталог Музейного фонда РФ",
            }
            new += 1
        print(f"  {i:>3}/{len(qs)} {q[:40]:<40} найдено {total.group(1) if total else '?':>5}"
              f" | карточек {len(cards):>3} | новых {new:>3}", flush=True)
    br.close()

    rows = sorted(found.values(), key=lambda r: r["zagolovok"])
    if rows:
        with (OUT / "goskatalog_cards.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        with (OUT / "goskatalog_cards.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nуникальных предметов: {len(rows)}")
    print(f"→ {OUT / 'goskatalog_cards.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
