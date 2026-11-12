"""Шаг 3: правило выставления года версии 2 + исправление 1 847 записей ГАПК.

Согласовано пользователем 09.11.2026.

ЧТО БЫЛО СЛОМАНО. У 1 847 записей (ГАПК ф. 279 — 1 656, ф. 716 — 191) год выведен
правилом «нижний год дела = начало диапазона описи»: совпадает в 1 847 из 1 847.
Ширина самих диапазонов — от 46 до 223 лет, у 1 419 записей 125–149 лет. То есть все
дела описи получали один год её начала — величина без информации.
Год восстановим из заголовка лишь у 4 записей из 1 847.

ПРАВИЛО ВЕРСИИ 2:
  1. год дела берётся только из карточки/описи самого дела либо из даты, названной
     в заголовке дела;
  2. крайние даты ОПИСИ датой дела не являются и в поля года не пишутся — остаются
     в «Примечания»;
  3. вводится признак «Год: источник значения» (симметрично масштабу);
  4. «Год источника» догадкой не заполняется никогда;
  5. ⭐ предложение пользователя: при отсутствии даты ставить ИНТЕРВАЛ ДАТИРОВКИ СЕРИИ —
     но ТОЛЬКО если он УЖЕ интервала описи (иначе смысла нет). Замер: из 1 847 записей
     199 попадают в серию 23 (1906–1917 — интервал 11 лет вместо 125–175, резкий
     выигрыш), 383 — в серию 24 (XVIII — нач. XX в., ~200 лет, выигрыша нет),
     1 265 пока без серии.

ЧТО ДЕЛАЕТ СКРИПТ:
  --create-prop  создать свойство «Год: источник значения»;
  --apply        выставить признак всем 1 847; исправить 4 записи по заголовку;
                 поставить интервал серии там, где он уже; очистить год у остальных.

  python year_provenance_fix.py                      # сухой прогон
  python year_provenance_fix.py --create-prop
  python year_provenance_fix.py --apply [--no-clear]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
BASELINE = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects"
LOCK = Path(__file__).resolve().parent / ".year_fix.lock"
OTHER_LOCKS = [
    Path(__file__).resolve().parent / ".series23.lock",
    Path(__file__).resolve().parent / ".series24.lock",
    Path(__file__).resolve().parent / ".scale_prov.lock",
]
CATALOG_DS = "decdf63c-6f64-4852-ada2-65e72c79d9bc"
PROP = "Год: источник значения"
OPTIONS = [
    "из карточки дела",
    "из заголовка дела",
    "по датировке серии",
    "по крайним датам описи",
    "нет",
]

BY_OPIS = re.compile(r"крайни\w*\s+дат\w*\s+описи|по\s+крайним\s+датам", re.I)
OPIS_RANGE = re.compile(r"(1[5-9]\d{2})\s*[–—-]\s*(1[5-9]\d{2}|20\d{2})")
YEAR_IN_TEXT = re.compile(r"\b(1[5-9]\d{2})(?!\s*[–—-]\s*1[5-9]\d{2})")

#: датировка серий, пригодная как интервал. Берём только УЗКИЕ и документированные.
#: ключ — файл набора привязки, значение — (нижний, верхний, имя для журнала)
SERIES_DATING = {
    "a10_zemleustroystvo/link_set.jsonl": (1906, 1917, "серия 23, землеустроительные комиссии"),
}
#: ⚠️ Датировать надо по ОСНОВАНИЮ привязки, а не по серии вслепую. Проверка 09.11.2026:
#: из 199 записей серии 23 с дефектным годом 191 попали туда ТОЛЬКО по упоминанию
#: Крестьянского поземельного банка, а банк вёл операции с 1883 г., — значит интервал
#: 1906–1917 для них ЛОЖНО УЗОК. Правильная нижняя граница для них 1883.
STOLYPIN_TERM = re.compile(
    r"землеустро|разверстан|отруб|чересполосиц"
    r"|выдел\w*\s+(?:на|к)\s+(?:одно|един)|единоличн|укреплени\w*\s+надел|хуторск",
    re.IGNORECASE,
)
PEASANT_BANK = re.compile(
    r"крестьянск\w*\s+(?:поземельн|земельн)\w*\s+банк", re.IGNORECASE
)
BANK_PERIOD = (1883, 1917, "Крестьянский поземельный банк, операции с 1883 г.")
#: серии, чья датировка ШИРЕ описи — интервал от них не ставим
SERIES_TOO_WIDE = {
    "ural_gornozavod/ours.jsonl": "серия 24: XVIII — нач. XX в., шире описи",
}


def load_ids(rel: str) -> set[str]:
    p = ROOT / rel
    if not p.exists():
        return set()
    return {
        json.loads(ln)["page_id"]
        for ln in p.open(encoding="utf-8")
        if ln.strip() and json.loads(ln).get("page_id")
    }


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--create-prop", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--no-clear",
        action="store_true",
        help="не очищать год у записей без даты (только признак и правки)",
    )
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))

    if args.create_prop:
        ds = retry(lambda: c.data_sources.retrieve(data_source_id=CATALOG_DS))
        if PROP in ds["properties"]:
            print(f"свойство уже есть: {PROP}")
        else:
            retry(
                lambda: c.data_sources.update(
                    data_source_id=CATALOG_DS,
                    properties={
                        PROP: {"select": {"options": [{"name": o} for o in OPTIONS]}}
                    },
                )
            )
            print(f"свойство создано: {PROP}")

    narrow: dict[str, tuple[int, int, str]] = {}
    for rel, (lo, hi, label) in SERIES_DATING.items():
        for pid in load_ids(rel):
            narrow[pid] = (lo, hi, label)
    too_wide = set()
    for rel in SERIES_TOO_WIDE:
        too_wide |= load_ids(rel)

    actions: list[dict] = []
    stats: Counter = Counter()
    for line in BASELINE.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        f = rec.get("fields") or {}
        if not BY_OPIS.search(str(f.get("Примечания") or "")):
            continue
        pid = rec.get("page_id") or rec.get("id") or ""
        text = f"{f.get('Название источника') or ''} {f.get('Описание') or ''}"
        prim = str(f.get("Примечания") or "")
        m = OPIS_RANGE.search(prim)
        opis_w = int(m.group(2)) - int(m.group(1)) if m else None

        ys = [int(y) for y in YEAR_IN_TEXT.findall(text)]
        if ys:
            a = {"pid": pid, "kind": "из заголовка дела",
                 "lo": min(ys), "hi": max(ys), "was": f.get("Год создания (нижняя)"),
                 "name": text[:150]}
        elif pid in narrow:
            lo, hi, label = narrow[pid]
            if opis_w is not None and (hi - lo) >= opis_w:
                a = {"pid": pid, "kind": "по крайним датам описи",
                     "lo": None, "hi": None, "was": f.get("Год создания (нижняя)"),
                     "why": f"интервал серии ({hi - lo} л.) не уже описи ({opis_w} л.)",
                     "name": text[:150]}
            else:
                if not STOLYPIN_TERM.search(text) and PEASANT_BANK.search(text):
                    lo, hi, label = BANK_PERIOD
                a = {"pid": pid, "kind": "по датировке серии", "lo": lo, "hi": hi,
                     "was": f.get("Год создания (нижняя)"), "why": label,
                     "name": text[:150]}
        else:
            a = {"pid": pid, "kind": "по крайним датам описи",
                 "lo": None, "hi": None, "was": f.get("Год создания (нижняя)"),
                 "why": SERIES_TOO_WIDE.get("ural_gornozavod/ours.jsonl")
                 if pid in too_wide else "серии нет либо её датировка не уже описи",
                 "name": text[:150]}
        stats[a["kind"]] += 1
        actions.append(a)

    print(f"\nзаписей с годом по описи: {len(actions)}")
    for k, v in stats.most_common():
        print(f"  {v:6d}  → признак «{k}»")
    set_series = [a for a in actions if a["kind"] == "по датировке серии"]
    from_title = [a for a in actions if a["kind"] == "из заголовка дела"]
    to_clear = [a for a in actions if a["kind"] == "по крайним датам описи"]
    print(f"\nбудет поставлен интервал серии: {len(set_series)}")
    print(f"будет исправлено по заголовку: {len(from_title)}")
    print(f"будет ОЧИЩЕН год: {len(to_clear)}" + (" (отключено --no-clear)" if args.no_clear else ""))

    p = OUT / "year_fix_plan.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for a in actions:
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(f"→ {p}")

    print("\nисправления по заголовку:")
    for a in from_title:
        print(f"  {a['was']} → {a['lo']}" + (f"–{a['hi']}" if a["hi"] != a["lo"] else "")
              + f" | {a['name'][:105]}")
    if set_series:
        print(f"\nинтервал серии (пример, всего {len(set_series)}):")
        for a in set_series[:5]:
            print(f"  {a['was']} → {a['lo']}–{a['hi']} ({a['why']}) | {a['name'][:90]}")

    if not args.apply:
        print("\nбез --apply ничего не записано")
        return

    if LOCK.exists():
        sys.exit(f"уже идёт прогон ({LOCK.name})")
    busy = [q.name for q in OTHER_LOCKS if q.exists()]
    if busy:
        sys.exit("идёт другой прогон записи в Notion: " + ", ".join(busy) + " — жду")

    LOCK.write_text("year_fix", encoding="utf-8")
    try:
        n = 0
        for i, a in enumerate(actions, 1):
            if not a["pid"]:
                continue
            props: dict = {PROP: {"select": {"name": a["kind"]}}}
            if a["kind"] in ("из заголовка дела", "по датировке серии"):
                props["Год создания (нижняя)"] = {"number": a["lo"]}
                props["Год создания (верхняя)"] = {"number": a["hi"]}
            elif not args.no_clear:
                props["Год создания (нижняя)"] = {"number": None}
                props["Год создания (верхняя)"] = {"number": None}
                props["Год источника"] = {"number": None}
            retry(lambda pid=a["pid"], props=props: c.pages.update(page_id=pid, properties=props))
            n += 1
            if i % 200 == 0:
                print(f"  {i}/{len(actions)}: обработано {n}", flush=True)
        print(f"ИТОГО обработано: {n}")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
