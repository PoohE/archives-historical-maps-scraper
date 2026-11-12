"""Остаток эвристических масштабов: 199 записей РГБ — добор масштаба с карточки РГБ.

Контекст: из 338 нетривиальных «приближённо по типу» 139 разобраны 07.11.2026
(117 обоснованы как Стрельбицкий 1:420 000, 22 сняты). Остальные 199 — записи РГБ,
по которым было решено брать масштаб из каталога РГБ при перепрогоне. Это он.

robots.txt search.rsl.ru разрешает /ru/record. Пауза 1 с между запросами.

  python fix_rgb_scales_harvest.py collect   # собрать масштабы с карточек → plan.jsonl
  python fix_rgb_scales_harvest.py apply     # внести подтверждённые
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

SRC = Path(
    r"C:\Users\admin\AppData\Local\Temp\claude\D--IG-Dropbox-Andy-PoohV-Project-Claude"
    r"\7fbfb943-dfbd-4420-95d7-a7e98d81798e\scratchpad\heuristic_scales.jsonl"
)
OUTDIR = Path(__file__).resolve().parents[1] / "output" / "fix_scales"
DONE = OUTDIR / "done.jsonl"
PLAN = OUTDIR / "rgb_plan.jsonl"

SCALE_FIELD = "Масштаб (знаменатель)"
ORIG_FIELD = "Оригинальный масштаб"
UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)"}
SCALE_RE = re.compile(r"1\s*[:：]\s*(\d[\d\s \u00a0]{2,12})")


def plain(v: dict) -> str:
    t = v.get("type")
    if t == "rich_text":
        return "".join(r["plain_text"] for r in v["rich_text"])
    if t == "title":
        return "".join(r["plain_text"] for r in v["title"])
    if t == "url":
        return v["url"] or ""
    if t == "number":
        return "" if v["number"] is None else str(v["number"])
    return ""


def find_url(props: dict) -> str:
    for v in props.values():
        if v.get("type") == "url" and (v.get("url") or "").startswith("http"):
            return v["url"]
    for v in props.values():
        s = plain(v)
        if "search.rsl.ru" in s or "rusneb.ru" in s:
            m = re.search(r"https?://\S+", s)
            if m:
                return m.group(0).rstrip(".,;)")
    return ""


def card_source(url: str) -> str:
    """Откуда реально читать карточку.

    В записях каталога лежат ссылки НЭБ и Президентской библиотеки, а не РГБ.
    rusneb.ru отдаёт 403 (считает запрос VPN), поэтому идентификатор НЭБ
    000199_000009_NNNNNNNNN разворачиваем в карточку РГБ 01NNNNNNNNN —
    это тот же документ, robots.txt РГБ разрешает /ru/record.
    """
    if not url:
        return ""
    if "search.rsl.ru" in url:
        return url
    m = re.search(r"000199_000009_(\d{9})", url)
    if m:
        return f"https://search.rsl.ru/ru/record/01{m.group(1)}"
    if "prlib.ru/item/" in url:
        return url.replace("https://prlib.ru/", "https://www.prlib.ru/")
    return ""


def fetch(url: str) -> str | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def scale_from_card(html: str) -> tuple[int | None, str]:
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    win = ""
    m = re.search(r"Масштаб[^.;]{0,160}", text)
    if m:
        win = m.group(0)
        s = SCALE_RE.search(win)
        if s:
            return int(re.sub(r"\D", "", s.group(1))), win.strip()[:150]
    s = SCALE_RE.search(text)
    if s:
        return int(re.sub(r"\D", "", s.group(1))), (win or s.group(0)).strip()[:150]
    return None, win.strip()[:150]


def collect() -> None:
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))
    done = {json.loads(ln)["page_id"] for ln in DONE.open(encoding="utf-8")}
    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8")]
    left = [r for r in rows if r["page_id"] not in done]
    print(f"осталось записей: {len(left)}")

    out = []
    for i, r in enumerate(left, 1):
        page = retry(lambda: client.pages.retrieve(page_id=r["page_id"]))
        url = find_url(page["properties"])
        rec = {"page_id": r["page_id"], "name": r["name"], "year": r["year"],
               "heur": r["sc"], "orig": r["orig"], "url": url}
        src = card_source(url)
        rec["src"] = src
        if src:
            time.sleep(2.0 if "prlib" in src else 1.0)
            html = fetch(src)
            if html:
                sc, ctx = scale_from_card(html)
                rec["card_scale"] = sc
                rec["card_ctx"] = ctx
        out.append(rec)
        if i % 20 == 0:
            got = sum(1 for x in out if x.get("card_scale"))
            print(f"  {i}/{len(left)} — масштаб с карточки найден у {got}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    with PLAN.open("w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    got = [x for x in out if x.get("card_scale")]
    same = [x for x in got if str(x["card_scale"]) == str(x["heur"])]
    diff = [x for x in got if str(x["card_scale"]) != str(x["heur"])]
    nourl = [x for x in out if not x["url"]]
    print(f"\nмасштаб с карточки РГБ получен: {len(got)} из {len(out)}")
    print(f"  совпал с эвристикой (можно обосновать): {len(same)}")
    print(f"  РАСХОДИТСЯ с эвристикой (исправить):    {len(diff)}")
    print(f"без ссылки на карточку:                   {len(nourl)}")
    print(f"карточка без масштаба:                    {len(out) - len(got) - len(nourl)}")
    print(f"\nфайл плана: {PLAN}")
    for x in diff[:15]:
        print(f"  !! {x['name'][:60]} | эвр {x['heur']} → карточка {x['card_scale']}")


def apply_() -> None:
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))
    recs = [json.loads(ln) for ln in PLAN.open(encoding="utf-8") if json.loads(ln).get("card_scale")]
    print(f"к внесению: {len(recs)}")
    n = 0
    with DONE.open("a", encoding="utf-8") as jrn:
        for r in recs:
            props = {
                SCALE_FIELD: {"number": int(r["card_scale"])},
                ORIG_FIELD: {"rich_text": [{"type": "text", "text": {"content":
                             f"1:{r['card_scale']} — по карточке РГБ {r['url']} "
                             f"(прежде: {r['orig']})"[:1900]}}]},
            }
            retry(lambda: client.pages.update(page_id=r["page_id"], properties=props))
            jrn.write(json.dumps({"page_id": r["page_id"], "action": "по карточке РГБ",
                                  "new": r["card_scale"]}, ensure_ascii=False) + "\n")
            n += 1
            time.sleep(0.35)
            if n % 25 == 0:
                print(f"  внесено {n}/{len(recs)}")
    print(f"внесено записей: {n}")


if __name__ == "__main__":
    fix_stdout()
    mode = sys.argv[1] if len(sys.argv) > 1 else "collect"
    (collect if mode == "collect" else apply_)()
