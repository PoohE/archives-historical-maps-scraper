"""Правка масштабов, проставленных эвристикой «по типу источника».

Разбор 06–07.11.2026: 42 615 записей каталога (37 %) имеют «Оригинальный масштаб» вида
«приближённо по типу …». Для планов дач (1:8 400) и одновёрсток (1:42 000) догадка совпадает
с нормативом и не трогается. Остальные 338 записей разобраны вручную:

  * ГАПК ф. 716 оп. 5 дд. 161, 163, 164, 165, 193 — «Спец. карта Европейской России»
    (листы 124, 125, 127) — это карта И.А. Стрельбицкого, её масштаб 1:420 000,
    а эвристика опознала «специальную карту» как трёхвёрстку → ИСПРАВИТЬ на 420 000.
  * ГАПК ф. 279 оп. 7 дд. 2200, 2202, 2204, 2205, 2206 (1783 г.) и ф. 716 оп. 5 карты-схемы
    Гражданской войны — масштаб по описи не приведён, тип определён неверно → СНЯТЬ число.
  * ПГКБ — то же, снять.
  * РГБ (≈311 записей) не трогаем: их масштаб будет взят из каталога РГБ при перепрогоне.

Режимы: plan | apply | verify

  python fix_heuristic_scales.py plan
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env, log  # noqa: E402
from mezh_batch_tag import ENV_PATH, SLEEP, retry, rt  # noqa: E402
from notion_client import Client  # noqa: E402

import time  # noqa: E402

SRC = Path(
    r"C:\Users\admin\AppData\Local\Temp\claude\D--IG-Dropbox-Andy-PoohV-Project-Claude"
    r"\7fbfb943-dfbd-4420-95d7-a7e98d81798e\scratchpad\heuristic_scales.jsonl"
)
DONE = Path(__file__).resolve().parents[1] / "output" / "fix_scales" / "done.jsonl"

SCALE_FIELD = "Масштаб (знаменатель)"
ORIG_FIELD = "Оригинальный масштаб"
NOTE_FIELD = "Примечания по оцифровке"

import re  # noqa: E402

# «Специальная карта Европейской России» И.А. Стрельбицкого — 10 вёрст в дюйме = 1:420 000.
# Часть записей несёт прямое указание («под редакцией ген. штаба генерал-лейтенанта
# Стрельбицкого»), часть — номера листов (58, 63, 90, 106, 107, 124–128, 136–143),
# соответствующие номенклатуре этой карты (177 листов).
STREL_NAME = re.compile(
    r"спец\w*\.?\s*карт\w*.{0,20}(европ|евр\.)|специальн\w*\s*\(\d+\).{0,20}(европ|евр\.)"
    r"|стрельбицк",
    re.I,
)
# Разнородные схемы Гражданской войны и карты 1783 г. — тип определён неверно, масштаба нет.
NO_SCALE_NAME = re.compile(
    r"карта[- ]схема|схема местности|топографическ\w* карт\w*[- ]?схем|"
    r"изданная с разрешения военно-топограф", re.I
)
NO_SCALE_DELA_279 = {"2200", "2202", "2204", "2205", "2206"}

NOTE_STREL = (
    "Масштаб атрибутирован 07.11.2026: «Специальная карта Европейской России» "
    "И.А. Стрельбицкого — 10 вёрст в английском дюйме = 1:420 000 (177 листов, 1865–1871, "
    "переиздания до 1930-х). Прежде значение стояло как догадка «приближённо по типу». "
    "Основание: наименование издания, номера листов в номенклатуре карты, у части записей — "
    "прямое указание редактора в заголовке дела."
)
NOTE_CLEAR = (
    "Масштаб снят 07.11.2026: числовое значение было проставлено эвристикой «по типу источника», "
    "в описи архива масштаб не приведён, а тип определён неверно. "
    "Заполнять только по описи или по измерению листа."
)


def decide(rec: dict) -> tuple[str, int | None, str] | None:
    """Вернуть (действие, новый масштаб, примечание) либо None, если запись не трогаем."""
    arch = str(rec.get("arch") or "")
    if arch == "РГБ":
        return None  # ждут перепрогона каталога РГБ с реальным масштабом
    if arch not in ("ГАПК", "ПГКБ"):
        return None
    name = str(rec.get("name") or "")
    if NO_SCALE_NAME.search(name):
        return ("снять", None, NOTE_CLEAR)
    if str(rec.get("f")) == "279" and str(rec.get("d")) in NO_SCALE_DELA_279:
        return ("снять", None, NOTE_CLEAR)
    if STREL_NAME.search(name):
        return ("обосновать", 420000, NOTE_STREL)
    return ("снять", None, NOTE_CLEAR)


def load_rows() -> list[dict]:
    return [json.loads(line) for line in SRC.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    rows = load_rows()

    plan = []
    for r in rows:
        d = decide(r)
        if d:
            plan.append((r, *d))

    print(f"записей-кандидатов в файле: {len(rows)}")
    print(f"к правке: {len(plan)}  (РГБ пропущено: "
          f"{sum(1 for r in rows if str(r.get('arch')) == 'РГБ')})")
    for action in ("обосновать", "снять"):
        grp = [p for p in plan if p[1] == action]
        changed = [p for p in grp if p[0].get("sc") != p[2]]
        print(f"\n  {action}: {len(grp)} (из них реально меняется число: {len(changed)})")
        for r, _a, new, _n in grp[:25]:
            cur = r.get("sc")
            mark = "  ←ИЗМЕНЕНИЕ" if cur != new else ""
            print(f"    {r['arch']} ф.{r['f']} оп.{r['o']} д.{r['d']}: "
                  f"1:{cur} → {('1:' + str(new)) if new else 'снять'}{mark} | {r['name'][:70]}")
        if len(grp) > 25:
            print(f"    … ещё {len(grp) - 25}")

    if mode != "apply":
        return

    DONE.parent.mkdir(parents=True, exist_ok=True)
    done_ids = set()
    if DONE.exists():
        for line in DONE.read_text(encoding="utf-8").splitlines():
            if line:
                done_ids.add(json.loads(line)["page_id"])

    client = Client(auth=env("NOTION_TOKEN"))
    written = 0
    with DONE.open("a", encoding="utf-8") as w:
        for r, action, new, note in plan:
            pid = r["page_id"]
            if pid in done_ids:
                continue
            props: dict = {
                SCALE_FIELD: {"number": new},
                ORIG_FIELD: {"rich_text": rt(
                    "не установлен по описи" if new is None
                    else "10 вёрст в дюйме (по атрибуции издания)"
                )},
                NOTE_FIELD: {"rich_text": rt(note)},
            }
            retry(lambda: client.pages.update(pid, properties=props))
            w.write(json.dumps({"page_id": pid, "action": action, "new": new},
                               ensure_ascii=False) + "\n")
            w.flush()
            written += 1
            time.sleep(SLEEP)
    log(f"записано правок: {written}")


if __name__ == "__main__":
    main()
