"""Дубли по узлу ПГКБ: одна книга — много записей, различающихся только ?fragment=page-N.

Что найдено 22.11.2026. В ссылке ПГКБ номер страницы просмотрщика стоит ПАРАМЕТРОМ
(`lib.permkrai.ru/node/24853?fragment=page-14`), а словарный улов отмечал каждую страницу,
на которой сработал запрос. Дедуп по `url equals` такие записи не склеивает — адреса
действительно разные, — и в каталог ушло по нескольку записей на одну книгу:

  39 записей — «Список населенных мест Пермской губернии. 5. Красноуфимский уезд»
  19 записей — «Географический и статистический словарь Пермской губернии (А - I)»
  15 записей — «Список населенных мест Пермской губернии. 3. Ирбитский уезд»
  13 записей — «Пермская губерния: учебник географии…»
  …

Всего по живым страницам набора 4.1: 50 узлов, 240 записей, из них 190 лишних. Заголовки
внутри каждой группы совпадают полностью (проверено по всем 116 группам пакета — расхождений
нет), класс и поля те же: это один источник, а не разные листы. «Единица каталога — лист
серии» здесь не применяется: fragment=page-N — страница ПРОСМОТРЩИКА, а не библиографическая
единица (память feedback_edinica-kataloga-list-serii-ne-obekt).

Способ снятия — как у технических дублей по каталогу (`dedupe_true_duplicates.py`,
`dedupe_gaso_notion.py`): оставляем созданную ПЕРВОЙ, остальным ставим «Статус приёмки» =
«отклонено» с причиной и ссылкой на оставленную. Физически не удаляем — в отличие от
485 дублей моста, которые были побайтовыми копиями от сбоя связи и в каталоге не значили
ничего (`trash_dubli_2026_11_22.py`).

  python scripts/dedupe_permkrai_fragment_2026_11_22.py --dry-run
  python scripts/dedupe_permkrai_fragment_2026_11_22.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
W = ROOT / "output" / "upload_2026-11-22-series"
STATE = W / "pages_state.jsonl"
TRASHED = W / "decisions" / "trashed_pages.jsonl"
REJECTED = W / "decisions" / "rejected_out_of_scope.jsonl"
OUT = W / "decisions" / "dedup_permkrai_fragment.jsonl"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
STATUS = "отклонено"
MARK = "Снято 22.11.2026 как дубль по узлу ПГКБ"
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


def node_key(url: str) -> str:
    """Адрес книги без страницы просмотрщика и без ссылки на скачивание PDF."""
    u = re.sub(r"[?&]fragment=page-\d+", "", url or "").rstrip("/")
    return re.sub(r"/pdfbook/download/.*$", "", u)


def jsonl_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(x)["page_id"] for x in path.open(encoding="utf-8") if x.strip()}


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    trash, rej, done = jsonl_ids(TRASHED), jsonl_ids(REJECTED), jsonl_ids(OUT)
    groups: dict[str, list[dict]] = defaultdict(list)
    for ln in STATE.open(encoding="utf-8"):
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("in_trash") or r["page_id"] in trash or r["page_id"] in rej:
            continue
        url = r.get("url") or ""
        if "lib.permkrai.ru" not in url:
            continue
        groups[node_key(url)].append(r)

    pairs: list[tuple[str, str, str, int]] = []   # (снять, оставить, узел, размер группы)
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda x: (x.get("created") or "", x["page_id"]))
        keep = rows[0]
        for r in rows[1:]:
            pairs.append((r["page_id"], keep["page_id"], key, len(rows)))

    keep_ids = {p[1] for p in pairs}
    drop_ids = {p[0] for p in pairs}
    if drop_ids & keep_ids or any(p[0] == p[1] for p in pairs):
        sys.exit("ОСТАНОВ: список дублей противоречив — запись и снимается, и остаётся")

    print(f"узлов ПГКБ с несколькими записями: {len({p[2] for p in pairs})}")
    print(f"  записей к отклонению: {len(pairs)} | уже отклонено ранее: "
          f"{len(drop_ids & done)}")
    todo = [p for p in pairs if p[0] not in done]
    print(f"  к обработке: {len(todo)}")
    if args.dry_run:
        for drop, keep, key, n in todo[:5]:
            print(f"    {key} (в группе {n}): снял бы {drop}, оставил {keep}")
        print("\n(проба) ничего не изменено")
        return

    load_env(ENV_PATH)
    token = env("NOTION_TOKEN")
    ok = already = errors = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for n, (drop, keep, key, size) in enumerate(todo, 1):
            p = api("GET", f"/pages/{drop}", token)
            if p.get("_missing") or p.get("in_trash"):
                continue
            props = p.get("properties") or {}
            cur = plain(props.get("Примечания"))
            if MARK in cur:
                already += 1
                continue
            keep_url = api("GET", f"/pages/{keep}", token).get("url", "")
            note = (f"{MARK}: та же книга, что в оставленной записи — различается только "
                    f"номер страницы просмотрщика в ссылке (?fragment=page-N). Узел: {key}; "
                    f"в улове было {size} записей на одну книгу. Оставлена созданная первой: "
                    f"{keep_url}. Запись сохранена для воспроизводимости отбора, не удалена.")
            note = (cur.rstrip() + " " + note).strip() if cur.strip() else note
            try:
                api("PATCH", f"/pages/{drop}", token, {"properties": {
                    "Статус приёмки": {"select": {"name": STATUS}},
                    "Примечания": {"rich_text": [
                        {"type": "text", "text": {"content": note[:2000]}}]}}})
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"  [{n}] ОШИБКА {drop}: {type(exc).__name__}: {exc}")
                continue
            ok += 1
            f.write(json.dumps({"page_id": drop, "keep": keep, "node": key,
                                "date": "2026-11-22"}, ensure_ascii=False) + "\n")
            f.flush()
            if n % 25 == 0:
                print(f"  обработано {n}/{len(todo)} | отклонено {ok}")
    print(f"\nотклонено: {ok} | пометка уже стояла: {already} | ошибок: {errors}")


if __name__ == "__main__":
    main()
