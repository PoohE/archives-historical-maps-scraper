"""Добор 504 карточек РГО (elib.rgo.ru) — хост поднялся 09.11.2026.

Эти карточки остались несобранными: при прогоне 08–09.11 `harvest_cards.py` помечал
их «хост недоступен (НЭБ 403 / РГО лежит)» — сайт отдавал 502 через российские прокси
и таймаут напрямую. Проверка `host_probe.py` 09.11.2026: **РГО отвечает 200 за 389 мс**.

elib.rgo.ru — DSpace, карточка по адресу `/handle/123456789/<id>`. Берём из неё
заголовок, масштаб, шифр/идентификатор и выходные данные из таблицы метаданных.

Пишет в ОТДЕЛЬНЫЙ файл, чтобы не портить прежнюю выгрузку; слияние — отдельным шагом.
Возобновляемый: повторный запуск добирает только то, чего нет в выходном файле.

  python harvest_rgo.py [--limit N]
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

DIR = Path(__file__).resolve().parents[1] / "output" / "work_2026-11-08"
WORK = DIR / "work.jsonl"
OUT = DIR / "harvested_rgo.jsonl"
LOCK = Path(__file__).resolve().parent / ".harvest_rgo.lock"

UA = {
    "User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru,en;q=0.8",
}
DELAY = 1.5
DEAD_AFTER = 6
NL = chr(10)  # перевод строки; chr() — чтобы не ломался при правке heredoc'ом

SC = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})")
# ⚠️ DSpace 6.2 у РГО отдаёт метаданные НЕ таблицей, а парами «Подпись :&nbsp; значение»
# в тексте, причём значение ДВАЖДЫ экранировано (&#x20; внутри уже раскрытого &nbsp;).
# Поэтому берём видимый текст и режем его по известным подписям.
LABELS = (
    "Библиографическое описание",
    "Заглавие/название",
    "Дата публикации",
    "Шифр хранения",
    "URI (Унифицированный идентификатор ресурса)",
    "Авторы",
    "Аннотация",
    "Масштаб",
    "Располагается в коллекциях",
)
TAILS = (" - Электронная библиотека РГО", " | Электронная библиотека РГО")


def strip_tags(s: str) -> str:
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def fetch(url: str) -> str | None:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=40
        ) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def parse(html: str) -> dict:
    out: dict = {}
    # 1) мета-теги — самое надёжное
    meta_tags = dict(
        re.findall(r'<meta\s+(?:name|property)="([^"]+)"\s+content="([^"]*)"', html)
    )
    for src, dst in (("DC.title", "zagolovok_polnyi"), ("citation_date", "god"),
                     ("DC.creator", "avtor"), ("citation_pdf_url", "pdf")):
        if meta_tags.get(src):
            out[dst] = unescape(meta_tags[src])[:300]

    # 2) видимый текст: пары «Подпись :&nbsp; значение»
    body = html
    for tag in ("script", "style"):
        # без обратной ссылки: в не-raw строке «\1» превращается в \x01
        body = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", body, flags=re.S | re.I)
    txt = unescape(unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))))
    txt = re.sub(r"\s+", " ", txt)
    fields: dict[str, str] = {}
    hits = sorted(
        ((m.start(), m.group(1)) for lab in LABELS
         for m in re.finditer(re.escape(lab) + r"\s*:\s*(.*)", txt)),
        key=lambda x: x[0],
    )
    for lab in LABELS:
        m = re.search(re.escape(lab) + r"\s*:\s*", txt)
        if not m:
            continue
        rest = txt[m.end():]
        # значение кончается там, где начинается следующая известная подпись
        ends = [rest.index(x) for x in LABELS if x in rest and rest.index(x) > 0]
        val = rest[: min(ends)] if ends else rest[:300]
        val = val.strip(" .;|—-")
        if val:
            fields[lab] = val[:400]
    if fields:
        out["meta"] = fields
    if fields.get("Шифр хранения"):
        out["shelf"] = fields["Шифр хранения"]
    if fields.get("Библиографическое описание"):
        out["istochnik"] = fields["Библиографическое описание"]
    if fields.get("Заглавие/название") and not out.get("zagolovok_polnyi"):
        out["zagolovok_polnyi"] = fields["Заглавие/название"]

    # 3) масштаб — из библиографического описания, заглавия или прямой подписи
    blob = " ".join([out.get("zagolovok_polnyi", ""), out.get("istochnik", ""),
                     fields.get("Масштаб", "")])
    w = re.search(r"Масштаб[^.;]{0,160}", blob) or re.search(r"Масштаб[^.;]{0,160}", txt)
    s = SC.search(w.group(0)) if w else SC.search(blob)
    if s:
        out["scale"] = int(re.sub(r"\D", "", s.group(1)))
        out["scale_ctx"] = (w.group(0) if w else s.group(0)).strip()[:120]
    _ = hits
    return out


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if LOCK.exists():
        sys.exit(f"уже идёт прогон ({LOCK.name})")
    if not WORK.exists():
        sys.exit(f"нет файла работы: {WORK}")

    rows = [json.loads(ln) for ln in WORK.open(encoding="utf-8") if ln.strip()]
    rgo = [r for r in rows if r["key"].split(":", 1)[0] == "РГО"]
    done: set[str] = set()
    if OUT.exists():
        for ln in OUT.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["key"])
            except (json.JSONDecodeError, KeyError):
                continue
    todo = [r for r in rgo if r["key"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"карточек РГО: {len(rgo)} | уже добрано: {len(done)} | к обходу: {len(todo)}",
          flush=True)

    LOCK.write_text("harvest_rgo", encoding="utf-8")
    fails = 0
    got = dead = 0
    try:
        with OUT.open("a", encoding="utf-8") as f:
            for i, r in enumerate(todo, 1):
                if "?offset=" in r["url"] or "/browse" in r["url"]:
                    skip_rec = {"key": r["key"], "url": r["url"],
                                "status": "не карточка (листинг коллекции)"}
                    f.write(json.dumps(skip_rec, ensure_ascii=False) + NL)
                    f.flush()
                    continue
                html = fetch(r["url"])
                if html is None:
                    fails += 1
                    dead += 1
                    f.write(json.dumps(
                        {"key": r["key"], "url": r["url"], "status": "не ответил"},
                        ensure_ascii=False) + "\n")
                    f.flush()
                    if fails >= DEAD_AFTER:
                        print(f"  {DEAD_AFTER} отказов подряд — хост снова лёг, останов "
                              f"на {i}/{len(todo)}", flush=True)
                        break
                else:
                    fails = 0
                    rec = {"key": r["key"], "url": r["url"], "status": "добрано",
                           **parse(html)}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    got += 1
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)}: добрано {got}, не ответили {dead}",
                          flush=True)
                time.sleep(DELAY)
    finally:
        LOCK.unlink(missing_ok=True)
    print(f"ИТОГО добрано: {got}; не ответили: {dead}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
