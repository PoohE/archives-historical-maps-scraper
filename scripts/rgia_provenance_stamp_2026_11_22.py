"""Пометка провенанса на 441 записи РГИА — исполнение варианта 2 (решение 22.11.2026).

Решение. У `fgurgia.ru` в robots.txt строкой 678 стоит адресный запрет для ИИ-агентов
(`User-agent: anthropic-ai → Disallow: /`). 441 запись из статистических фондов РГИА была
внесена 15.11 до того, как запрет заметили. Из трёх вариантов — письмо в архив, оставить с
пометкой о провенансе, откатить — А. Алейников выбрал второй, владелец подтвердил:
«оставить внесённое с пометкой о провенансе и дальше не ходить» (DECISIONS.md, 22.11.2026).

Что делает скрипт. К полю «Примечания» каждой из 441 страницы дописывает одну строку о
происхождении данных. Существующий текст примечаний сохраняется: пометка добавляется в
конец, а не вместо. Повторный прогон безопасен — страница с уже стоящей пометкой
пропускается по её тексту, а не по журналу (журналы заливок 22.11 оказались неполными, см.
verify_pages_by_id_2026_11_22.py).

Чего скрипт НЕ делает: не ходит на fgurgia.ru и ничего оттуда не читает. 807 карточек
очереди и лесные фонды 379, 387, 515 не добираются — это часть того же решения.

  python scripts/rgia_provenance_stamp_2026_11_22.py --dry-run
  python scripts/rgia_provenance_stamp_2026_11_22.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JRN = ROOT / "output" / "upload_2026-11-16" / "rgia_review_run" / "created_pages.jsonl"
OUT = ROOT / "output" / "upload_2026-11-16" / "rgia_provenance_stamped.jsonl"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
NOTE = ("Провенанс: метаданные сняты с публичного портала РГИА (fgurgia.ru) 15.11.2026 — "
        "только открытые описания дел; образы и закрытые данные не запрашивались, защита "
        "сайта не обходилась. Решение владельца 22.11.2026: запись сохраняется с этой "
        "пометкой, дальнейший машинный сбор на портале не ведётся.")
MARK = "Провенанс: метаданные сняты с публичного портала РГИА"
RETRIES = 5
NOTION = "https://api.notion.com/v1"


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{NOTION}{path}", data=data, method=method,
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

    ids: list[str] = []
    for ln in JRN.open(encoding="utf-8"):
        if ln.strip():
            pid = json.loads(ln).get("page_id")
            if pid and pid not in ids:
                ids.append(pid)
    print(f"страниц РГИА в журнале 16.11: {len(ids)}")

    load_env(ENV_PATH)
    token = env("NOTION_TOKEN")
    stamped = already = skipped = errors = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for n, pid in enumerate(ids, 1):
            p = api("GET", f"/pages/{pid}", token)
            if p.get("_missing"):
                skipped += 1
                print(f"  [{n}] страница не найдена: {pid}")
                continue
            if p.get("in_trash") or p.get("archived"):
                skipped += 1
                continue
            cur = plain((p.get("properties") or {}).get("Примечания"))
            if MARK in cur:
                already += 1
                continue
            new = (cur.rstrip() + " " + NOTE).strip() if cur.strip() else NOTE
            if args.dry_run:
                stamped += 1
                if stamped <= 3:
                    print(f"  [{n}] поставил бы пометку: {pid}\n     было: {cur[:90]}\n"
                          f"     станет: {new[:160]}…")
                continue
            try:
                api("PATCH", f"/pages/{pid}", token, {
                    "properties": {"Примечания": {
                        "rich_text": [{"type": "text", "text": {"content": new[:2000]}}]}}})
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"  [{n}] ОШИБКА {pid}: {type(exc).__name__}: {exc}")
                continue
            stamped += 1
            f.write(json.dumps({"page_id": pid, "date": "2026-11-22"},
                               ensure_ascii=False) + "\n")
            f.flush()
            if n % 50 == 0:
                print(f"  обработано {n}/{len(ids)} | помечено {stamped} | уже было {already}")
    tag = "(проба) " if args.dry_run else ""
    print(f"\n{tag}помечено: {stamped} | пометка уже стояла: {already} | "
          f"пропущено (нет/в корзине): {skipped} | ошибок: {errors}")


if __name__ == "__main__":
    main()
