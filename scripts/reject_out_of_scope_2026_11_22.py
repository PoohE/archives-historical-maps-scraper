"""Отклонение 270 записей пакета 4.1, оказавшихся вне скоупа (решение владельца 22.11.2026).

Как они попали в каталог. Решение владельца по набору 4.1 звучало так: периодика и тексты
1918 года и позже — отсев, классы «карта» и «статистика» — в каталог целиком. Сборщик это и
сделал, но граница 1918 к картам и статистике не применилась вовсе, а территориальный гейт
пропустил чужие губернии: в улове словарей поиска по нашим губерниям оказались издания,
где название нашей губернии стоит в тексте, а предмет — чужая территория.

Три группы (журнал `decisions/vne_skoupa_k_resheniyu.csv`):
  * 73 — год 1918 и позже, территория наша (Атлас Смоленской области 1964/1994/1997,
    Схема пассажирского транспорта Перми 1988 и подобное);
  * 168 — чужая губерния, год в скоупе (Архангельская, Пензенская, Костромская, Тамбовская,
    Новгородская, Псковская, Олонецкая, Вятская, Оренбургская, Владимирская, Цивильский уезд
    Казанской, вплоть до Варшавской и Эриванской);
  * 29 — и то и другое.

Чего в этих 270 НЕТ намеренно: 135 обзорных источников по Российской империи, Европейской
России и СССР — по правилу межгубернских они идут в relation «Европейская Россия», а не в
отсев (`rule_territory_multiprovince`); и 11 записей по Уралу под советскими и горнозаводскими
именами (Ирбитский и Кунгурский округа, Екатеринбургский горный округ) — это Пермская
губерния, они наши.

Способ отсева — «Статус приёмки» = «отклонено» с причиной в примечании, не удаление: это
принятый в проекте обычай для вне-скоупного (`dedupe_gaso_notion.py`,
`dedupe_true_duplicates.py`, правило «отсев — не мусор»). Запись остаётся видимой, решение
воспроизводимо, и будущие прогоны не предложат её заново.

Номера страниц берутся из `pages_state.jsonl` — сверки по номерам, а не из журнала заливки:
журнал 22.11 оказался неполным, а фильтрованный запрос к базе теряет свежие записи
(см. verify_pages_by_id_2026_11_22.py).

  python scripts/reject_out_of_scope_2026_11_22.py --dry-run
  python scripts/reject_out_of_scope_2026_11_22.py --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
W = ROOT / "output" / "upload_2026-11-22-series"
LIST = W / "decisions" / "vne_skoupa_k_resheniyu.csv"
STATE = W / "pages_state.jsonl"
OUT = W / "decisions" / "rejected_out_of_scope.jsonl"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
URL_COL = "Ссылка на онлайн-архив"
STATUS = "отклонено"
MARK = "Отклонено 22.11.2026 как вне скоупа"
REASON = {
    "год 1918 и позже": (f"{MARK}: год создания 1918 или позже — вне хронологических границ "
                         "проекта (XVIII — начало XX в.). Решение владельца по набору 4.1; "
                         "запись сохранена для воспроизводимости отбора, а не удалена."),
    "чужая губерния": (f"{MARK}: предмет источника — губерния вне четырёх наших (Калужская, "
                       "Смоленская, Ярославская, Пермская). В улов попал потому, что название "
                       "нашей губернии встречается в тексте издания. Запись сохранена для "
                       "воспроизводимости отбора, а не удалена."),
    "чужая губерния и 1918+": (f"{MARK}: и чужая губерния, и год создания 1918 или позже. "
                               "Запись сохранена для воспроизводимости отбора, а не удалена."),
}
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

    # ссылка -> живые номера страниц
    pages: dict[str, list[str]] = {}
    for ln in STATE.open(encoding="utf-8"):
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("in_trash"):
            continue
        pages.setdefault((r.get("url") or "").rstrip("/"), []).append(r["page_id"])

    rows = list(csv.DictReader(LIST.open(encoding="utf-8-sig")))
    done = set()
    if OUT.exists():
        done = {json.loads(l)["page_id"] for l in OUT.open(encoding="utf-8") if l.strip()}

    targets: list[tuple[str, str, str]] = []   # (page_id, группа, название)
    no_page: list[str] = []
    for r in rows:
        key = r[URL_COL].strip().rstrip("/")
        ids = pages.get(key)
        if not ids:
            no_page.append(r[URL_COL])
            continue
        for pid in ids:
            targets.append((pid, r["_группа"], r["Название источника"]))

    print(f"в списке вне скоупа: {len(rows)}")
    print(f"  найдено живых страниц: {len(targets)}")
    print(f"  ссылок без живой страницы: {len(no_page)} (должно быть 0)")
    for u in no_page[:5]:
        print(f"    {u}")
    todo = [t for t in targets if t[0] not in done]
    print(f"  уже отклонено ранее: {len(targets) - len(todo)}")
    print(f"  к отклонению: {len(todo)}")

    load_env(ENV_PATH)
    token = env("NOTION_TOKEN")
    ok = already = errors = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for n, (pid, grp, title) in enumerate(todo, 1):
            p = api("GET", f"/pages/{pid}", token)
            if p.get("_missing") or p.get("in_trash"):
                continue
            props = p.get("properties") or {}
            cur = plain(props.get("Примечания"))
            if MARK in cur:
                already += 1
                continue
            note = (cur.rstrip() + " " + REASON[grp]).strip() if cur.strip() else REASON[grp]
            if args.dry_run:
                ok += 1
                if ok <= 3:
                    print(f"  [{n}] отклонил бы: {title[:60]}\n     группа: {grp}")
                continue
            try:
                api("PATCH", f"/pages/{pid}", token, {"properties": {
                    "Статус приёмки": {"select": {"name": STATUS}},
                    "Примечания": {"rich_text": [
                        {"type": "text", "text": {"content": note[:2000]}}]}}})
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"  [{n}] ОШИБКА {pid}: {type(exc).__name__}: {exc}")
                continue
            ok += 1
            f.write(json.dumps({"page_id": pid, "группа": grp, "date": "2026-11-22"},
                               ensure_ascii=False) + "\n")
            f.flush()
            if n % 50 == 0:
                print(f"  обработано {n}/{len(todo)} | отклонено {ok}")
    tag = "(проба) " if args.dry_run else ""
    print(f"\n{tag}отклонено: {ok} | пометка уже стояла: {already} | ошибок: {errors}")


if __name__ == "__main__":
    main()
