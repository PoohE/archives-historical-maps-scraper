"""Разбор 131 записи каталога с пустым «Статусом приёмки» (24.11.2026, поручение владельца).

Откуда: выгрузка 23.11 после закрытия кандидатов — 94 записи РГАВМФ, 20 СОУНБ (Свердловск),
12 планов городов НЭБ без держателя, 5 КОНБ. Статус им не поставили при заливке.

Решение — те же правила, что у кандидатов (`kandidaty_reshenie_2026_11_23.decide`), плюс
ручные поправки ниже (каждая с причиной). Запись: только страницы, у которых статус всё ещё
пуст; причина дописывается в «Примечания»; журнал по page id; затем сверка опросом.

  python scripts/pustoy_status_2026_11_24.py output/notion_catalog_<метка>.csv --dry-run
  python scripts/pustoy_status_2026_11_24.py output/notion_catalog_<метка>.csv
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kandidaty_apply_2026_11_23 import ENV_PATH, api, plain  # noqa: E402
from kandidaty_reshenie_2026_11_23 import decide, norm  # noqa: E402
from common import env, fix_stdout, load_env  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "pustoy_status_2026-11-24"
MARK = "Разбор пустого статуса 24.11.2026: "
DUP = "точный дубль принятой записи (та же ссылка и заголовок)"

# Поправки к правилам: подстрока в заголовке -> (решение, причина)
MANUAL = [
    ("Над старинными рукописями", "принять",
     "издано в 1972, данные — конец XVIII в.: год печати ≠ год данных (как у переписи 1917, "
     "решение владельца 23.11)"),
    ("Смоленское наместничество. Духовщина. План города", "принять",
     "план эпохи наместничества; год 1955 был взят из размера листа «Формат 2440 х 1955» — "
     "год очищен"),
    ("План Города Рословля", "принять", "Рославль — Смоленская губерния"),
    ("План Города Поречья", "принять", "Поречье — Смоленская губерния"),
    ("План Города Белого", "принять", "Белый — Смоленская губерния"),
    ("План Города Краснаго", "принять", "Красный — Смоленская губерния"),
    ("74-пушечный корабль", "отклонить", "чертёж корабля — привязки к территории нет"),
    ("транспорта Молога", "отклонить", "«Молога» — название судна, привязки к территории нет"),
    ("План Петрограда", "отклонить", "Петроград — не наши губернии"),
    ("водозабора насосной станции Соликамского комбината", "отклонить",
     "советский проект — после 1917, вне скоупа"),
    ("Карта Можайского, Боровского, Зубтсовского и Вяземского уездов", "принять",
     "межгубернская: Боровский уезд — Калужская, Вяземский — Смоленская губерния"),
]
YEAR_FIX = "Смоленское наместничество. Духовщина. План города"
YEAR_FIELDS = ["Год создания (нижняя)"]          # «Год источника» — формула от него, пересчитается
YEAR_CHECK = ["Год создания (нижняя)", "Год источника"]


def build(snapshot: str) -> list[dict]:
    csv.field_size_limit(10**9)
    allr = list(csv.DictReader(open(snapshot, encoding="utf-8-sig")))
    seen = {(r["Ссылка на онлайн-архив"], norm(r["Название источника"]))
            for r in allr if r["Статус приёмки"] == "принято" and r["Ссылка на онлайн-архив"]}
    out = []
    for r in allr:
        if r["Статус приёмки"]:
            continue
        t = r["Название источника"]
        man = next(((d, w) for k, d, w in MANUAL if k in t), None)
        if (r["Ссылка на онлайн-архив"], norm(t)) in seen:
            d, w = "отклонить", DUP
        elif man:
            d, w = man
        else:
            d, w = decide(r)
        out.append({"page_id": r["page_id"], "держатель": r["Архив [авто]"], "решение": d,
                    "причина": w, "год_очистить": "да" if YEAR_FIX in t else "",
                    "Название источника": t, "Ссылка на онлайн-архив": r["Ссылка на онлайн-архив"]})
    return out


def empty_value(ptype: str) -> dict:
    return {"number": None} if ptype == "number" else {ptype: []} if ptype in (
        "rich_text", "multi_select") else {ptype: None}


def apply(rows: list[dict], token: str) -> None:
    jpath = OUT / "journal.jsonl"
    done = {json.loads(x)["page_id"] for x in jpath.open(encoding="utf-8")} if jpath.exists() else set()
    with jpath.open("a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            if r["page_id"] in done:
                continue
            p = api("GET", f"/pages/{r['page_id']}", token)
            props = p.get("properties", {})
            st = ((props.get("Статус приёмки") or {}).get("select") or {}).get("name")
            if p.get("_missing") or p.get("in_trash") or st:
                res = f"пропущено: {'нет страницы' if p.get('_missing') or p.get('in_trash') else st}"
            else:
                status = "принято" if r["решение"] == "принять" else "отклонено"
                note = plain(props.get("Примечания")).rstrip()
                add = f"{MARK}{status} — {r['причина']}"
                body = {"Статус приёмки": {"select": {"name": status}},
                        "Примечания": {"rich_text": [{"type": "text", "text": {
                            "content": ((note + "\n" + add) if note else add)[:2000]}}]}}
                if r["год_очистить"]:
                    for k in YEAR_FIELDS:
                        body[k] = empty_value(props[k]["type"])
                api("PATCH", f"/pages/{r['page_id']}", token, {"properties": body})
                res = "ok"
            f.write(json.dumps({"page_id": r["page_id"], "решение": r["решение"], "итог": res},
                               ensure_ascii=False) + "\n")
            f.flush()


def val(prop: dict):
    v = prop.get(prop["type"])
    return v.get(v.get("type")) if prop["type"] == "formula" else v


def verify(rows: list[dict], token: str) -> None:
    want = {"принять": "принято", "отклонить": "отклонено"}
    bad = []
    for r in rows:
        p = api("GET", f"/pages/{r['page_id']}", token)
        props = p.get("properties", {})
        st = ((props.get("Статус приёмки") or {}).get("select") or {}).get("name")
        ok = st == want[r["решение"]] and MARK in plain(props.get("Примечания"))
        if r["год_очистить"]:
            ok = ok and all(not val(props[k]) for k in YEAR_CHECK)
        if not ok:
            bad.append((r["page_id"], st))
    print(f"сверка опросом: {len(rows) - len(bad)} из {len(rows)} верно; расхождения: {bad}")


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = build(a.snapshot)
    with (OUT / "reshenie.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"записей: {len(rows)} | {dict(Counter(r['решение'] for r in rows))}")
    for k, v in Counter((r["держатель"] or "(без держателя)", r["решение"]) for r in rows).items():
        print(f"  {k}: {v}")
    if a.dry_run:
        return
    load_env(ENV_PATH)
    token = env("NOTION_TOKEN", required=True)
    apply(rows, token)
    verify(rows, token)


if __name__ == "__main__":
    main()
