"""Сбор каталога Архивного фонда Ярославской области (af.yar-archives.ru).

Маршрут (разведка 14.10.2026): портал закрыт WAF для нероссийских адресов, поиск защищён
reCAPTCHA, а КАТАЛОГ ФОНДОВ открыт и капчи не просит. robots.txt разрешает всё
(`User-agent: * / Disallow:`), поимённых запретов ИИ-агентам нет. Страницы открывает
браузер пользователя (его IP), скрипт снимает уже отрисованный DOM по протоколу отладки.

Структура портала (Yii2 GridView, строго 20 записей на страницу, per-page игнорируется):
    /archive<A>/funds?page=N                 список фондов архива A
    /archive<A>/funds?FundSearch[FUND_NAME_SHORT]=межев   фильтр по названию
    /archive<A>/funds/<fund_id>              фонд → ссылки на описи
    /archive<A>/inventory/<inv_id>?page=N    опись → дела
    /archive<A>/unit/<unit_id>               дело

Режимы:
    --archives            перечислить архивы портала (arc=1..12)
    --funds A[,B,...]     полные списки фондов указанных архивов
    --opisi               описи отобранных фондов (вход — selected_funds.json)
    --dela                дела всех описей (вход — opisi.jsonl)
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
HOST = "af.yar-archives.ru"
LOAD_WAIT = 3.5      # только на первичную отрисовку постоянной вкладки
DELAY = 1.0          # пауза между запросами — портал областного архива не нагружать
PER_PAGE = 20        # жёстко задано порталом, per-page не слушается

OUT = Path(__file__).resolve().parents[1] / "output" / "gayo"
TAG = re.compile(r"<[^>]+>")
# ⚠️ разряды отбиты СУЩНОСТЬЮ `&nbsp;` («5&nbsp;252»), а не пробелом: без неё в классе
# символов числа от тысячи не матчились и крупные архивы молча отсеивались (поймано 14.10)
SUMMARY = re.compile(r"Показаны записи\s*<b>(.{1,20}?)</b>\s*из\s*<b>(.{1,20}?)</b>", re.S)
ROW = re.compile(r'<tr data-key="(\d+)">(.*?)</tr>', re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
HREF = re.compile(r'href="([^"]+)"')
CAM = re.compile(r'glyphicon-camera"\s*title="([^"]*)"')


def clean(s: str) -> str:
    return re.sub(r"[\s ]+", " ", H.unescape(TAG.sub(" ", s))).strip()


def num(s: str) -> int:
    d = re.sub(r"[^\d]", "", s)
    return int(d) if d else 0


# ---------------------------------------------------------------- CDP


def cdp(path: str, method: str = "GET"):
    req = urllib.request.Request(f"{CDP}{path}", method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def open_tab(url: str) -> dict:
    # адрес уходит в query самого CDP → кодировать ЦЕЛИКОМ, иначе обрыв на первом &
    return cdp("/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")


def close_tab(tid: str) -> None:
    try:
        cdp(f"/json/close/{tid}")
    except Exception:  # noqa: BLE001, S110
        pass


def dom_of(ws_url: str) -> str | None:
    import websocket

    ws = websocket.create_connection(ws_url, timeout=40, suppress_origin=True)
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


class Session:
    """Одна постоянная вкладка на сайте; страницы берём внутри неё обычным fetch.

    Открывать вкладку на каждую страницу оказалось вчетверо дороже самой страницы
    (~15 с против ~3 с, замер 14.10): браузер каждый раз заново тянет шрифты, метрику
    и recaptcha. Запрос из уже открытой страницы идёт тем же origin и с теми же куками,
    но без перерисовки — и серверу это дешевле, чем полная загрузка вкладки.
    """

    def __init__(self) -> None:
        self.tab = open_tab(f"https://{HOST}/archive1/funds")
        time.sleep(LOAD_WAIT)
        self.ws_url = self.tab["webSocketDebuggerUrl"]
        self._ws = None

    def _conn(self):
        import websocket

        if self._ws is None:
            self._ws = websocket.create_connection(self.ws_url, timeout=60,
                                                   suppress_origin=True)
        return self._ws

    def get(self, url: str, tries: int = 3) -> str | None:
        """Вернуть HTML или None. Признак капчи выставляется отдельно (CAPTCHA_HIT):
        транспортный сбой и заслон портала — разные вещи, смешивать их нельзя,
        иначе один таймаут веб-сокета останавливает весь заход (поймано 14.10)."""
        expr = (f"fetch({json.dumps(url)}, {{credentials:'include'}})"
                ".then(r => r.text())")
        for attempt in range(1, tries + 1):
            try:
                ws = self._conn()
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "awaitPromise": True,
                                               "returnByValue": True}}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == 1:
                        break
                html = msg.get("result", {}).get("result", {}).get("value")
                if html and "form-captcha" in html:
                    print("  ⚠️ КАПЧА на", url, flush=True)
                    globals()["CAPTCHA_HIT"] = True
                    return None
                # ⚠️ судить по размеру нельзя: серверный HTML ~25 КБ, тогда как снятый
                # DOM был ~340 КБ (разницу дают инлайн-стили и скрипты). Проверяем смысл.
                # Маркеры разные у разных страниц: список — GridView с data-key, карточка
                # фонда — таблица «Описи фонда» БЕЗ data-key (на этом 29 фондов из 30
                # молча ушли в «страница не получена», 14.10).
                if html and ('data-key="' in html or "Показаны записи" in html
                             or "Описи фонда" in html or "/inventory/" in html):
                    return html
                print(f"  пустой ответ ({len(html or '')}) на {url}")
            except Exception as e:  # noqa: BLE001
                self._ws = None  # соединение могло отвалиться — пересоздать
                if attempt == tries:
                    print(f"  ошибка {type(e).__name__} на {url}")
            finally:
                time.sleep(DELAY)
        return None

    def close(self) -> None:
        """Закрыть свою вкладку — но НИКОГДА последнюю: на последней Chrome закрывает
        окно, и пользователь остаётся с пустым браузером (поймано 16.10). Сессия при
        этом выживает, но работать не с чем."""
        try:
            if self._ws:
                self._ws.close()
        finally:
            try:
                pages = [t for t in cdp("/json/list") if t.get("type") == "page"]
            except Exception:  # noqa: BLE001
                pages = []
            if self.tab.get("id") and len(pages) > 1:
                close_tab(self.tab["id"])


SESSION: Session | None = None
CAPTCHA_HIT = False


def fetch(url: str, tries: int = 3) -> str | None:
    global SESSION  # noqa: PLW0603
    if SESSION is None:
        SESSION = Session()
    return SESSION.get(url, tries)


def body(html: str) -> str:
    """Содержательная часть страницы — без шапки портала и подвала."""
    a = html.find("<h1")
    b = html.find("Контактная информация")
    return html[a if a > 0 else 0: b if b > 0 else len(html)]


def total_of(html: str) -> int:
    m = SUMMARY.search(html)
    return num(H.unescape(m.group(2))) if m else 0


def grid_rows(html: str) -> list[list[str]]:
    """Строки GridView: ячейки как есть (с разметкой — нужны href и признак образов).

    ⚠️ Содержимое строки — ГРУППА 2: группа 1 у ROW это data-key. На `r[1]` разбор молча
    давал ноль ячеек при двадцати найденных строках (поймано 14.10 на первом же прогоне).
    """
    return [CELL.findall(r[2]) for r in ROW.finditer(body(html))]


class Budget:
    """Квота запросов на заход. Портал пускает ~60–70 обращений на сессию независимо от
    темпа, поэтому порцию надо останавливать самим, а не упираться в капчу."""

    def __init__(self, limit: int = 0) -> None:
        self.limit = limit
        self.used = 0
        self.blocked = False

    def spend(self) -> bool:
        if self.limit and self.used >= self.limit:
            return False
        self.used += 1
        return True

    @property
    def left(self) -> int:
        return max(0, self.limit - self.used) if self.limit else 10 ** 9


BUDGET = Budget()


def paged(url_base: str, total: int, label: str, first_page: int = 1):
    """Пройти постраничную выдачу GridView. Отдаёт пары (номер страницы, html)."""
    pages = max(1, -(-total // PER_PAGE))
    for p in range(first_page, pages + 1):
        if not BUDGET.spend():
            print(f"  {label}: квота захода исчерпана на стр. {p}/{pages}", flush=True)
            return
        sep = "&" if "?" in url_base else "?"
        html = fetch(f"{url_base}{sep}page={p}")
        if not html:
            print(f"  {label}: стр. {p}/{pages} не получена", flush=True)
            if CAPTCHA_HIT:
                BUDGET.blocked = True
                return
            yield p, None  # транспортный сбой: страницу помечаем пропущенной и идём дальше
            continue
        yield p, html
        if p % 25 == 0:
            print(f"  {label}: {p}/{pages} страниц", flush=True)


# ---------------------------------------------------------------- режимы


def mode_archives(out: Path) -> int:
    res = []
    for a in range(1, 31):
        html = fetch(f"https://{HOST}/archive{a}/funds")
        if not html:
            continue
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
        name = clean(m.group(1)) if m else ""
        tot = total_of(html)
        if not name or not tot:
            continue
        res.append({"arc": a, "name": name, "funds": tot})
        print(f"archive{a}: {name} — {tot} фондов")
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {out}")
    return 0


def fund_rows(html: str, arc: int) -> list[dict]:
    out = []
    for cells in grid_rows(html):
        if len(cells) < 3:
            continue
        href = HREF.search(cells[1])
        cam = CAM.search(cells[3]) if len(cells) > 3 else None
        out.append({"arc": arc, "fund_num": clean(cells[0]), "title": clean(cells[1]),
                    "dates": clean(cells[2]),
                    "fund_id": href.group(1).rsplit("/", 1)[-1] if href else "",
                    "digitized": clean(cam.group(1)) if cam else "",
                    "vybyl": "Фонд выбыл" in cells[1]})
    return out


def mode_funds(arcs: list[int], out: Path) -> int:
    """Полные списки фондов. Пишем по ходу: прогон длинный, обрыв не должен стоить всего."""
    done = set()
    if out.exists():  # возобновляемость по архивам
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["arc"])
        print(f"уже собраны архивы: {sorted(done)}")
    total = 0
    with out.open("a", encoding="utf-8") as f:
        for a in arcs:
            if a in done:
                continue
            base = f"https://{HOST}/archive{a}/funds"
            first = fetch(base)
            if not first:
                print(f"archive{a}: первая страница не получена")
                continue
            tot = total_of(first)
            print(f"archive{a}: {tot} фондов, {-(-tot // PER_PAGE)} страниц", flush=True)
            n, empty = 0, 0
            for _p, html in paged(base, tot, f"archive{a}"):
                if html is None:
                    continue
                got = fund_rows(html, a)
                if not got:  # страница пришла, а строк нет — это дефект разбора, не норма
                    empty += 1
                for r in got:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    n += 1
                f.flush()
            if empty:
                print(f"  ⚠️ страниц без строк: {empty}", flush=True)
            total += n
            print(f"archive{a}: записано {n} из {tot}", flush=True)
    print(f"\nдобавлено фондов: {total} → {out}")
    return 0


def mode_filter(arcs: list[int], words: list[str], out: Path) -> int:
    """Дешёвая альтернатива полному обходу: фильтр GridView по названию фонда."""
    seen, rows = set(), []
    for a in arcs:
        for w in words:
            q = urllib.parse.quote(w)
            base = (f"https://{HOST}/archive{a}/funds"
                    f"?FundSearch%5BFUND_NAME_SHORT%5D={q}")
            first = fetch(base)
            if not first:
                continue
            tot = total_of(first)
            if not tot:
                continue
            for _p, html in paged(base, tot, f"a{a}/{w}"):
                if html is None:
                    continue
                for r in fund_rows(html, a):
                    key = (r["arc"], r["fund_id"])
                    if r["fund_id"] and key not in seen:
                        seen.add(key)
                        r["matched"] = w
                        rows.append(r)
            print(f"archive{a} «{w}»: {tot}", flush=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nуникальных фондов по фильтрам: {len(rows)} → {out}")
    return 0


TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
INV_HREF = re.compile(r"/archive\d+/inventory/(\d+)")


def opis_rows(html: str) -> list[dict]:
    """Описи с карточки фонда: таблица с подписью «Описи фонда», строки БЕЗ data-key."""
    b = body(html)
    start = b.find("Описи фонда")
    chunk = b[start:] if start > 0 else b
    end = chunk.find("</table>")
    if end > 0:
        chunk = chunk[:end]
    out, seen_ids = [], set()
    for tr in TR.finditer(chunk):
        m = INV_HREF.search(tr.group(1))
        if not m or m.group(1) in seen_ids:
            continue
        seen_ids.add(m.group(1))
        out.append({"inv_id": m.group(1),
                    "cells": [clean(c) for c in CELL.findall(tr.group(1))]})
    if not out:  # у части фондов опись одна и подана ссылкой вне таблицы
        for m in INV_HREF.finditer(b):
            if m.group(1) not in seen_ids:
                seen_ids.add(m.group(1))
                out.append({"inv_id": m.group(1), "cells": []})
    return out


def annotation(html: str) -> str:
    """Аннотация фонда — архив сам перечисляет состав документов (ценный контекст отбора)."""
    b = body(html)
    i = b.find("Описи фонда")
    tail = b[i:] if i > 0 else b
    j = tail.find("</table>")
    if j < 0:
        return ""
    text = clean(tail[j:])
    return text[:2000]


def mode_opisi(src: Path, out: Path) -> int:
    funds = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"фондов к обходу: {len(funds)}")
    res = []
    for i, fd in enumerate(funds, 1):
        url = f"https://{HOST}/archive{fd['arc']}/funds/{fd['fund_id']}"
        html = fetch(url)
        if not html:
            print(f"{i:>4}/{len(funds)} Ф.{fd['fund_num']} — страница не получена")
            continue
        seen = opis_rows(html)
        ann = annotation(html)
        for s in seen:
            res.append({**fd, "inv_id": s["inv_id"], "inv_cells": s["cells"],
                        "fund_annotation": ann})
        print(f"{i:>4}/{len(funds)} Ф.{fd['fund_num']:<8} описей: {len(seen)}"
              + (f", аннотация {len(ann)} симв." if ann else ""), flush=True)
    with out.open("w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nвсего описей: {len(res)} → {out}")
    return 0


def mode_dela(src: Path, out: Path) -> int:
    """Сбор дел порциями. Состояние по каждой описи — в соседнем json, поэтому опись,
    прерванную на середине, следующий заход дочитывает, а не считает собранной
    (при учёте «описи, встреченной в выходном файле» потерялись бы её хвосты)."""
    opisi = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    state_path = out.with_name(out.stem + "_state.json")
    state: dict[str, dict] = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    ready = sum(1 for s in state.values() if s.get("done"))
    print(f"описей всего {len(opisi)}, из них дочитано {ready}", flush=True)

    def save_state() -> None:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    with out.open("a", encoding="utf-8") as f:
        for i, op in enumerate(opisi, 1):
            key = op["inv_id"]
            st = state.setdefault(key, {"pages": 0, "total": 0, "rows": 0, "done": False})
            if st["done"]:
                continue
            if BUDGET.left <= 1:
                print("квота захода исчерпана — останавливаюсь штатно", flush=True)
                break
            base = f"https://{HOST}/archive{op['arc']}/inventory/{key}"
            tot = st.get("total") or 0
            if not tot:  # первую страницу читаем только ради общего числа дел
                if not BUDGET.spend():
                    break
                first = fetch(base)
                if not first:
                    print(f"{i:>4}/{len(opisi)} оп.{key} — не получена", flush=True)
                    if CAPTCHA_HIT:
                        BUDGET.blocked = True
                        break
                    continue
                tot = total_of(first)
                st["total"] = tot
            n = 0
            last = st["pages"]
            for p, html in paged(base, tot, f"оп.{key}", first_page=st["pages"] + 1):
                if html is None:
                    st.setdefault("missed", []).append(p)
                    st["pages"] = p
                    last = p
                    save_state()
                    continue
                for cells in grid_rows(html):
                    if len(cells) < 3:
                        continue
                    href = HREF.search(cells[1])
                    cam = CAM.search(cells[4]) if len(cells) > 4 else None
                    f.write(json.dumps({
                        "arc": op["arc"], "fund_num": op["fund_num"],
                        "fund_title": op["title"], "inv_id": key,
                        "inv_cells": op.get("inv_cells", []),
                        "unit_num": clean(cells[0]), "title": clean(cells[1]),
                        "dates": clean(cells[2]),
                        "sheets": clean(cells[3]) if len(cells) > 3 else "",
                        "unit_id": href.group(1).rsplit("/", 1)[-1] if href else "",
                        "digitized": clean(cam.group(1)) if cam else "",
                    }, ensure_ascii=False) + "\n")
                    n += 1
                f.flush()
                last = p
                st["pages"], st["rows"] = p, st["rows"] + 0  # фиксируем прогресс сразу
                save_state()
            st["rows"] += n
            pages_total = max(1, -(-tot // PER_PAGE))
            # пропущенные из-за сбоя страницы помним поимённо: иначе «дочитано» соврёт
            got = set(range(1, st["pages"] + 1)) - set(st.get("missed", []))
            st["done"] = last >= pages_total and len(got) >= pages_total
            save_state()
            mark = "✓" if st["done"] else f"… {last}/{pages_total} стр."
            if st.get("missed"):
                mark += f", пропущено {len(st['missed'])}"
            print(f"{i:>4}/{len(opisi)} Ф.{op['fund_num']:<8} оп.{key}: +{n} дел из {tot} {mark}",
                  flush=True)
            if BUDGET.blocked:
                print("портал попросил проверку — останавливаюсь", flush=True)
                break

    done_now = sum(1 for s in state.values() if s.get("done"))
    rows_now = sum(s.get("rows", 0) for s in state.values())
    print(f"\nзапросов за заход: {BUDGET.used}"
          f"\nописей дочитано: {done_now}/{len(opisi)}"
          f"\nдел собрано всего: {rows_now}"
          f"\n→ {out}\n→ {state_path}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--archives", action="store_true")
    ap.add_argument("--funds", default="", help="номера архивов через запятую, напр. 1,3,4")
    ap.add_argument("--filter", default="", help="номера архивов для фильтра по названию")
    ap.add_argument("--words", default="карт,план,межев,земл,чертеж,геодез,топограф,съемк,статистич")
    ap.add_argument("--opisi", default="", help="jsonl отобранных фондов")
    ap.add_argument("--dela", default="", help="jsonl описей")
    ap.add_argument("--out", default="")
    ap.add_argument("--delay", type=float, default=None,
                    help="пауза между запросами, с. Портал метит сессию капчей примерно "
                         "с 50 запросов/мин; проверенно безопасно ≈12/мин, рабочее — 8 с")
    ap.add_argument("--max-requests", type=int, default=0,
                    help="квота запросов на заход (портал пускает ~60–70 на сессию)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.delay:
        globals()["DELAY"] = args.delay
    if args.max_requests:
        BUDGET.limit = args.max_requests
        print(f"квота захода: {args.max_requests} запросов", flush=True)
    print(f"темп: 1 запрос в {DELAY} с (~{60 / DELAY:.0f} в минуту)", flush=True)

    if args.archives:
        return mode_archives(Path(args.out) if args.out else OUT / "archives.json")
    if args.funds:
        arcs = [int(x) for x in args.funds.split(",") if x.strip()]
        return mode_funds(arcs, Path(args.out) if args.out else OUT / "funds_all.jsonl")
    if args.filter:
        arcs = [int(x) for x in args.filter.split(",") if x.strip()]
        words = [w.strip() for w in args.words.split(",") if w.strip()]
        return mode_filter(arcs, words, Path(args.out) if args.out else OUT / "funds_filtered.jsonl")
    if args.opisi:
        return mode_opisi(Path(args.opisi), Path(args.out) if args.out else OUT / "opisi.jsonl")
    if args.dela:
        try:
            return mode_dela(Path(args.dela),
                             Path(args.out) if args.out else OUT / "dela.jsonl")
        finally:
            # вкладку за собой закрываем: иначе за вечер их накапливается десяток
            # и в окне браузера не разобраться (замечание пользователя 14.10)
            if SESSION is not None:
                SESSION.close()
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
