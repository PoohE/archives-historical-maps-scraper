"""ГАКО: обход профильных фондов через браузер пользователя (CDP), без прямых запросов.

Режим согласован с пользователем 13.10.2026: страницы грузит его Chrome, скрипт только
управляет вкладками по локальному порту отладки и снимает готовый DOM. Сам скрипт в сеть
не ходит (archive.admoblkaluga.ru в robots.txt запрещает ИИ-агентам прямой обход).

Две фазы:
  --funds  по странице каждого фонда: какие описи, есть ли у них дела в базе и скан описи;
  --dela   по описям, где дела ЕСТЬ: списки дел постранично (searchObjectType=12924).

Подготовка: Chrome запущен с --remote-debugging-port=9222 (окно открывает пользователь
или главная сессия).

Запуск:
    python -B scripts_gako/gako_harvest.py --funds --links C:\\arch\\gako_in\\ОПИСИ_ГАКО_ссылки.md \
        --out C:\\arch\\output\\gako_harvest_20261013
    python -B scripts_gako/gako_harvest.py --dela --out C:\\arch\\output\\gako_harvest_20261013
"""
from __future__ import annotations

import argparse
import html as H
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9222"
HOST = "archive.admoblkaluga.ru"
DELAY = 2.5                    # пауза между страницами — портал областного архива не нагружать
LOAD_WAIT = 4.0                # сколько ждать дорисовку AJAX-содержимого

TAG = re.compile(r"<[^>]+>")
OPIS_LINK = re.compile(r"/gako/object/(\d+)\?params=[^\"']*?\"?[^>]*>\s*(Ф\.\s*[^<]{5,160})", re.S)
DELO_COUNT = re.compile(r"Дело\s*\((\d+)\)")
DELO_ROW = re.compile(r"Ф\.\s*([А-ЯЁ]?-?\d+[а-я]?)\s*Оп\.\s*([\w\-/]+)\s*Д\.\s*(\d+[а-я]?)\s*([^<]{0,400})")
COUNT = re.compile(r"Результаты поиска:\s*[\d\-–]+\s*из\s*(\d+)")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(TAG.sub(" ", s))).strip()


def cdp(path: str, method: str = "GET"):
    req = urllib.request.Request(f"{CDP}{path}", method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def open_tab(url: str) -> dict:
    # ⚠️ Адрес уходит в QUERY самого CDP (`/json/new?<url>`), поэтому кодировать надо
    # ЦЕЛИКОМ: при safe="&=" первый же амперсанд обрывал ссылку, и вместо списка описей
    # открывалась пустая страница поиска (поймано 13.10: все фонды дали по нулю описей).
    return cdp("/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")


def close_tab(tid: str) -> None:
    try:
        cdp(f"/json/close/{tid}")
    except Exception:  # noqa: BLE001, S110
        pass


def dom_of(ws_url: str) -> str | None:
    import websocket

    ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": "document.documentElement.outerHTML",
                                       "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                return msg.get("result", {}).get("result", {}).get("value")
    finally:
        ws.close()


def fetch(url: str, wait: float = LOAD_WAIT) -> str | None:
    """Открыть вкладку в браузере пользователя, дождаться отрисовки, снять DOM, закрыть."""
    tab = open_tab(url)
    tid = tab.get("id")
    try:
        time.sleep(wait)
        return dom_of(tab["webSocketDebuggerUrl"])
    finally:
        if tid:
            close_tab(tid)
        time.sleep(DELAY)


def opis_list_url(opis_id: str) -> str:
    """Список ДЕЛ описи: searchObjectType=12924 (у описей — 12922)."""
    return (f"https://{HOST}/gako/search?type=custom&searchObjectType=12924"
            f"&p0.d={opis_id}&p0.v={opis_id}&p0.a=13350&p0.c=10&pageSize=100")


def mode_funds(links_md: Path, out: Path) -> int:
    rows = []
    for line in links_md.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*\|\s*Ф\.\s*([^\s|]+)\s*\|\s*(\d+)\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*(\S+)\s*\|", line)
        if m:
            rows.append({"fund": m.group(1), "n_opisi": int(m.group(2)),
                         "tags": m.group(3).strip(), "title": m.group(4).strip(),
                         "url": m.group(5).strip()})
    print(f"фондов к обходу: {len(rows)}")

    res = []
    for i, r in enumerate(rows, 1):
        html = fetch(r["url"])
        if not html:
            print(f"{i:>3}/{len(rows)} Ф.{r['fund']:<8} DOM не получен")
            continue
        opisi = []
        for oid, label in OPIS_LINK.findall(html):
            lab = clean(label)
            if "Оп." in lab and not any(o["id"] == oid for o in opisi):
                opisi.append({"id": oid, "label": lab[:160]})
        dela_counts = [int(x) for x in DELO_COUNT.findall(html)]
        has_scan = html.count("imageViewer")
        res.append({**r, "opisi": opisi, "dela_counts": dela_counts, "scan_links": has_scan})
        print(f"{i:>3}/{len(rows)} Ф.{r['fund']:<8} описей {len(opisi):>2}  "
              f"дел в базе {sum(dela_counts):>5}  сканов {has_scan}")

    out.mkdir(parents=True, exist_ok=True)
    f = out / "gako_funds_probe.jsonl"
    with f.open("w", encoding="utf-8") as fh:
        for r in res:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with_dela = [r for r in res if sum(r["dela_counts"])]
    print(f"\nфондов с делами в базе: {len(with_dela)}; "
          f"дел суммарно: {sum(sum(r['dela_counts']) for r in res)}")
    print(f"итог: {f}")
    return 0


def mode_dela(out: Path) -> int:
    probe = out / "gako_funds_probe.jsonl"
    rows = [json.loads(ln) for ln in probe.open(encoding="utf-8") if ln.strip()]
    targets = [(r, o) for r in rows if sum(r["dela_counts"]) for o in r["opisi"]]
    print(f"описей к выгрузке: {len(targets)}")

    all_dela, seen = [], set()
    for i, (fund, opis) in enumerate(targets, 1):
        page = 1
        while True:
            # Пагинация у портала именная: параметр называется page<searchObjectType>,
            # для списка дел это `page12924` (не `page`/`pageNum` — те игнорируются,
            # и выдача молча остаётся первой страницей).
            url = opis_list_url(opis["id"]) + (f"&page12924={page}" if page > 1 else "")
            html = fetch(url)
            if not html:
                break
            total = COUNT.search(html)
            n_total = int(total.group(1)) if total else 0
            got = 0
            for f_, o_, n_, tail in DELO_ROW.findall(html):
                key = (f_, o_, n_)
                if key in seen:
                    continue
                seen.add(key)
                all_dela.append({"fund": f_, "opis": o_, "n_delo": n_,
                                 "zagolovok": clean(tail) or None,
                                 "opis_label": opis["label"], "opis_id": opis["id"]})
                got += 1
            print(f"{i:>3}/{len(targets)} {opis['label'][:50]:<52} стр.{page}: "
                  f"+{got} (всего в описи {n_total})")
            if got == 0 or len(seen) >= n_total or page > 30:
                break
            page += 1

    f = out / "gako_dela.jsonl"
    with f.open("w", encoding="utf-8") as fh:
        for r in all_dela:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with_title = sum(1 for r in all_dela if r["zagolovok"])
    print(f"\nдел собрано: {len(all_dela)}, с заголовком: {with_title}")
    print(f"итог: {f}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", action="store_true")
    ap.add_argument("--dela", action="store_true")
    ap.add_argument("--links", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        cdp("/json/version")
    except Exception:  # noqa: BLE001
        print("Chrome с отладкой не отвечает на 127.0.0.1:9222")
        return 1

    out = Path(args.out)
    if args.funds:
        return mode_funds(Path(args.links), out)
    if args.dela:
        return mode_dela(out)
    print("укажите --funds или --dela")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
