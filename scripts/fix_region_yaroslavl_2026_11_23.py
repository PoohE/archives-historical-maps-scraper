"""Снятие лишней связи «Современные регионы» = Ярославская область (23.11.2026).

Повод. Сессия article-34 при разборе каталога нашла 83 записи Малоярославецкого уезда
(Калужская губерния) с Ярославской областью в «Современных регионах» — похоже на ловушку
«топоним внутри слова» (малоЯРОСЛАВецкий). Замер по выгрузке 15.11 дал больше: 403 записи,
где заголовок называет только наши ДРУГИЕ губернии, а регион стоит ярославский.

Но 280 из 403 — не дефект, а ошибка ПРОВЕРКИ. Это записи ГАЯО, фонд 455 «Ярославский
губернский межевой архив»: «межевая книга дачи пустоши Лапковой села Рославлево» —
ярославское село, а территориальный гейт читает «Рославлево» как смоленский Рославль.
Провенанс здесь сильнее подстроки, поэтому записи ГАЯО не трогаются вовсе. Та же ловушка,
что в памяти feedback_gate-declension-and-substring-traps, только с другой стороны: не гейт
пропустил чужое, а гейт объявил чужим своё.

Правятся 123 записи, где держатель НЕ ГАЯО и ярославской связи взяться неоткуда:
РГИА 82 (в том числе опись 10 ф. 380 — целиком Калужская губерния по аннотации архива),
Госкаталог 26, Президентская библиотека 7, ГАКО 3, РГАДА 2, ГПИБ 2, РГБ 1.

Как снимается. У каждой страницы перечитывается ЖИВОЕ состояние: связь снимается только
если (а) ярославская связь ещё стоит, (б) архив записи не ГАЯО, (в) заголовок называет
нашу губернию и это не Ярославская. Остальные регионы записи сохраняются. В «Примечания»
дописывается строка о правке — чтобы потом было видно, что регион менялся и почему.

  python scripts/fix_region_yaroslavl_2026_11_23.py --dry-run
  python scripts/fix_region_yaroslavl_2026_11_23.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from territory_gate import our_gubernii  # noqa: E402

from common import env, fix_stdout, load_env  # noqa: E402

OUT = ROOT / "output"
BASELINE = OUT / "notion_catalog_20261115_121359_baseline.jsonl"
RELATIONS = OUT / "notion_catalog_20261115_121359_relations.json"
JOURNAL = OUT / "fix_region_yaroslavl_2026-11-23.jsonl"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
MARK = "Правка 23.11.2026: снята связь «Современные регионы» = Ярославская область"
SKIP_ARCHIVES = ("ГАЯО",)        # провенанс ярославский — связь законна
RETRIES = 5


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Notion-Version": "2025-09-03",
                 "Content-Type": "application/json"})
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"_missing": True}
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 ** attempt * 0.4)
    raise last  # type: ignore[misc]


def plain(prop: dict) -> str:
    return "".join(x.get("plain_text", "") for x in (prop or {}).get("rich_text", []))


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    regs = json.loads(RELATIONS.read_text(encoding="utf-8"))["Современные регионы"]
    yar = {i for t, i in regs.items() if "Ярославск" in t}
    name_of = {i: t for t, i in regs.items()}

    cand: list[tuple[str, str, str]] = []     # (page_id, архив, губерния по заголовку)
    for ln in BASELINE.open(encoding="utf-8"):
        r = json.loads(ln)
        f = r["fields"]
        ids = f.get("Современные регионы") or []
        if not any(i in yar for i in ids):
            continue
        arch = str(f.get("Архив [авто]") or f.get("Место хранения") or "")
        if any(a in arch for a in SKIP_ARCHIVES):
            continue
        text = (f.get("Название источника") or "") + " " + (f.get("Описание") or "")
        gub = set(our_gubernii(text))
        if not gub or "Ярославская" in gub:
            continue
        cand.append((r["page_id"], arch, "+".join(sorted(gub))))

    done: set[str] = set()
    if JOURNAL.exists():
        done = {json.loads(x)["page_id"] for x in JOURNAL.open(encoding="utf-8") if x.strip()}
    todo = [c for c in cand if c[0] not in done]
    print(f"кандидатов по выгрузке 15.11 (без ГАЯО): {len(cand)}")
    print(f"  уже поправлено ранее: {len(cand) - len(todo)} | к правке: {len(todo)}")
    print(f"  по архивам: {dict(Counter(a for _, a, _ in todo))}")
    print(f"  по губернии из заголовка: {dict(Counter(g_ for *_, g_ in todo))}")

    load_env(ENV_PATH)
    token = env("NOTION_TOKEN")
    fixed = skipped = errors = 0
    f_out = None if args.dry_run else JOURNAL.open("a", encoding="utf-8", newline="\n")
    try:
        for n, (pid, arch, gub) in enumerate(todo, 1):
            p = api("GET", f"/pages/{pid}", token)
            if p.get("_missing") or p.get("in_trash"):
                skipped += 1
                continue
            props = p.get("properties") or {}
            cur = [x["id"] for x in (props.get("Современные регионы") or {}).get("relation", [])]
            if not any(i in yar for i in cur):
                skipped += 1              # связь уже снята кем-то другим
                continue
            keep = [i for i in cur if i not in yar]
            title = "".join(x.get("plain_text", "")
                            for x in (props.get("Название источника") or {}).get("title", []))
            if args.dry_run:
                fixed += 1
                if fixed <= 5:
                    print(f"    [{n}] {arch} | {gub} | было: "
                          f"{[name_of.get(i, i[:8]) for i in cur]} → станет: "
                          f"{[name_of.get(i, i[:8]) for i in keep] or 'пусто'}")
                    print(f"         {title[:95]}")
                continue
            note = plain(props.get("Примечания"))
            why = (f"{MARK}: держатель {arch or 'не указан'}, по заголовку территория — "
                   f"{gub} губерния. Связь была поставлена по совпадению подстроки в слове "
                   "(«малоЯРОСЛАВецкий» и подобные). Остальные регионы записи сохранены.")
            new_note = (note.rstrip() + " " + why).strip() if note.strip() else why
            try:
                api("PATCH", f"/pages/{pid}", token, {"properties": {
                    "Современные регионы": {"relation": [{"id": i} for i in keep]},
                    "Примечания": {"rich_text": [
                        {"type": "text", "text": {"content": new_note[:2000]}}]}}})
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"  [{n}] ОШИБКА {pid}: {type(exc).__name__}: {exc}")
                continue
            fixed += 1
            f_out.write(json.dumps({"page_id": pid, "архив": arch, "губерния": gub,
                                    "снято": [name_of.get(i, i) for i in cur if i in yar],
                                    "осталось": [name_of.get(i, i) for i in keep],
                                    "date": "2026-11-23"}, ensure_ascii=False) + "\n")
            f_out.flush()
            if n % 25 == 0:
                print(f"  обработано {n}/{len(todo)} | поправлено {fixed}")
    finally:
        if f_out:
            f_out.close()
    tag = "(проба) " if args.dry_run else ""
    print(f"\n{tag}поправлено: {fixed} | пропущено: {skipped} | ошибок: {errors}")
    if not args.dry_run:
        print(f"журнал: {JOURNAL}")


if __name__ == "__main__":
    main()
