"""Правки каталога по замечаниям сессии анализа (article-34) — общий исполнитель (24.11.2026).

Постоянное указание владельца 24.11: замечания исправлять сразу; каждая правка — с журналом по
page id, отметкой в «Примечаниях» и сверкой опросом после записи. Записи не удаляем.

Вход — CSV правок (utf-8): page_id; set — JSON {поле: значение}; note — что исправлено и почему.
Значение null очищает поле. Тип поля берётся с живой страницы: number / select / rich_text /
relation (значение — заголовок записи справочника, id берётся из *_relations.json слепка).

  python scripts/fix_batch.py <правки.csv> <relations.json> --dry-run
  python scripts/fix_batch.py <правки.csv> <relations.json>
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kandidaty_apply_2026_11_23 import ENV_PATH, api, plain  # noqa: E402
from common import env, fix_stdout, load_env  # noqa: E402


def encode(ptype: str, field: str, v, rel: dict) -> dict:
    if ptype == "number":
        return {"number": v}
    if ptype == "select":
        return {"select": None if v is None else {"name": v}}
    if ptype == "rich_text":
        return {"rich_text": [] if v is None else [{"type": "text", "text": {"content": str(v)[:2000]}}]}
    if ptype == "relation":
        vals = [] if v is None else (v if isinstance(v, list) else [v])
        return {"relation": [{"id": rel[field][x]} for x in vals]}
    raise ValueError(f"тип {ptype} поля «{field}» не поддержан")


def current(prop: dict, field: str, rel: dict):
    t, v = prop["type"], prop.get(prop["type"])
    if t == "select":
        return (v or {}).get("name")
    if t == "rich_text":
        return plain(prop) or None
    if t == "relation":
        back = {i.replace("-", ""): k for k, i in rel.get(field, {}).items()}
        ids = [x["id"].replace("-", "") for x in v]
        names = [back.get(i, i) for i in ids]
        return None if not names else names[0] if len(names) == 1 else names
    return v


def norm(d: dict) -> dict:
    """Список из одного значения и строка — одно и то же; порядок значений связи не важен."""
    out = {}
    for k, v in d.items():
        if isinstance(v, list):
            v = sorted(v) if len(v) != 1 else v[0]
            v = v or None
        out[k] = v
    return out


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("fixes")
    ap.add_argument("relations")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.fixes, encoding="utf-8-sig")))
    rel = json.loads(Path(a.relations).read_text(encoding="utf-8"))
    for r in rows:                                   # проверить входы до записи
        for f, v in json.loads(r["set"]).items():
            if f in rel and any(x not in rel[f] for x in ([] if v is None else v if isinstance(v, list) else [v])):
                sys.exit(f"нет «{v}» в справочнике поля «{f}»")
    print(f"правок: {len(rows)}")
    if a.dry_run:
        return
    load_env(ENV_PATH)
    token = env("NOTION_TOKEN", required=True)
    jpath = Path(a.fixes).with_suffix(".journal.jsonl")
    done = {json.loads(x)["page_id"] for x in jpath.open(encoding="utf-8")} if jpath.exists() else set()
    with jpath.open("a", encoding="utf-8", newline="\n") as j:
        for r in rows:
            if r["page_id"] in done:
                continue
            p = api("GET", f"/pages/{r['page_id']}", token)
            if p.get("_missing") or p.get("in_trash"):
                j.write(json.dumps({"page_id": r["page_id"], "итог": "нет страницы"}, ensure_ascii=False) + "\n")
                continue
            props = p["properties"]
            body = {f: encode(props[f]["type"], f, v, rel) for f, v in json.loads(r["set"]).items()}
            old = {f: current(props[f], f, rel) for f in body}
            note = plain(props.get("Примечания")).rstrip()
            body["Примечания"] = encode("rich_text", "Примечания", ((note + "\n") if note else "") + r["note"], rel)
            api("PATCH", f"/pages/{r['page_id']}", token, {"properties": body})
            j.write(json.dumps({"page_id": r["page_id"], "было": old, "итог": "ok"}, ensure_ascii=False) + "\n")
            j.flush()
    bad = []
    for r in rows:                                   # сверка опросом
        props = api("GET", f"/pages/{r['page_id']}", token)["properties"]
        want = json.loads(r["set"])
        got = {f: current(props[f], f, rel) for f in want}
        if norm(got) != norm(want) or r["note"] not in plain(props.get("Примечания")):
            bad.append((r["page_id"], got))
    print(f"сверка опросом: {len(rows) - len(bad)} из {len(rows)} верно; расхождения: {bad}")


if __name__ == "__main__":
    main()
