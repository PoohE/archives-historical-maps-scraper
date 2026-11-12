"""Замер двух системных дефектов каталога: эвристический масштаб и год по описи.

Поводом служит разбор серии 24 (блок 24): в горнозаводском слое масштаб оказался
эвристическим у 83 % записей, а год у 383 записей взят по крайним датам описи.
Прежде чем чинить, надо понять масштаб беды по ВСЕМУ каталогу и — главное —
какая доля поправима ОФЛАЙН, прямо из заголовка записи.

Считает:
  1) сколько записей с масштабом «приближённо по типу» (эвристика), сколько с явным,
     сколько пусто — по каталогу целиком и по архивам;
  2) у скольких ЭВРИСТИЧЕСКИХ записей масштаб на самом деле НАПИСАН в заголовке
     («Масштаб 200 саженей», «100 саж. в дюйме», «м-1 в», «1:8400») — это и есть
     бесплатно поправимая доля;
  3) сколько записей с годом «по крайним датам описи» и у скольких из них год
     написан в заголовке или описании;
  4) отдельно — пересечение с горнозаводским слоем и серией 23.

Ничего не меняет: только печатает и пишет списки в output/defects/.

  python defects_audit.py [путь_к_baseline.jsonl]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
OUT = ROOT / "defects"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"

HEUR = re.compile(r"приближ|по типу", re.IGNORECASE)
YEAR_BY_OPIS = re.compile(r"крайни\w*\s+дат\w*\s+описи|по\s+крайним\s+датам", re.I)

# Масштаб, НАПИСАННЫЙ в тексте записи. Четыре формы, встречающиеся в описях.
SCALE_PATTERNS = [
    # «Масштаб 200 саженей», «200 саж. в дюйме», «100 саж/дюйм»
    (
        "саж",
        re.compile(
            r"(?:масштаб\w*\s*)?(\d{1,4})\s*саж(?:ен\w*|\.)?\s*"
            r"(?:в\s*(?:англ\w*\s*)?дюйм\w*|/\s*дюйм|в\s*дм)?",
            re.IGNORECASE,
        ),
    ),
    # «2 версты в дюйме», «м-1 в», «10 в/дюйм»
    (
        "верст",
        re.compile(
            r"(?:масштаб\w*\s*)?(\d{1,3})\s*(?:верст\w*|в\.)\s*"
            r"(?:в\s*(?:англ\w*\s*)?дюйм\w*|/\s*дюйм)",
            re.IGNORECASE,
        ),
    ),
    ("м-N в", re.compile(r"\bм-\s*(\d{1,3})\s*в\b", re.IGNORECASE)),
    ("1:N", re.compile(r"1\s*:\s*(\d{3,9})")),
]
# Год, НАПИСАННЫЙ в тексте записи
YEAR_IN_TEXT = re.compile(r"\b(1[6-9]\d{2}|19[0-5]\d)\s*(?:г\.|год|г\b)", re.IGNORECASE)


def scale_from_text(t: str) -> tuple[str, int] | None:
    """Вернуть (вид записи, знаменатель) если масштаб назван в тексте."""
    for kind, pat in SCALE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        v = int(m.group(1))
        if kind == "саж" and 1 <= v <= 2000:
            return kind, v * 84  # 1 саж/дюйм = 84 (7 футов / 1 дюйм)
        if kind in ("верст", "м-N в") and 1 <= v <= 200:
            return kind, v * 42000
        if kind == "1:N" and 100 <= v <= 100_000_000:
            return kind, v
    return None


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not src.exists():
        sys.exit(f"нет выгрузки: {src}")

    n = 0
    sc_state: Counter = Counter()
    sc_by_arch: Counter = Counter()
    yr_state: Counter = Counter()
    fixable_scale: list[dict] = []
    fixable_year: list[dict] = []
    scale_kinds: Counter = Counter()

    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        rec = json.loads(line)
        f = rec.get("fields") or {}
        pid = rec.get("page_id") or rec.get("id") or ""
        arch = (f.get("Архив [авто]") or "?").strip()
        name = str(f.get("Название источника") or "")
        desc = str(f.get("Описание") or "")
        prim = str(f.get("Примечания") or "")
        orig = str(f.get("Оригинальный масштаб") or "")
        text = f"{name} {desc}"

        # --- дефект 1: масштаб
        if HEUR.search(orig):
            state = "эвристика"
        elif orig:
            state = "указан в записи"
        elif f.get("Масштаб (знаменатель)"):
            state = "число без пояснения"
        else:
            state = "пусто"
        sc_state[state] += 1
        sc_by_arch[(arch, state)] += 1
        if state == "эвристика":
            got = scale_from_text(text)
            if got:
                scale_kinds[got[0]] += 1
                fixable_scale.append(
                    {
                        "page_id": pid,
                        "arch": arch,
                        "fond": str(f.get("Фонд") or ""),
                        "opis": str(f.get("Опись") or ""),
                        "delo": str(f.get("Единица хранения") or ""),
                        "was": f.get("Масштаб (знаменатель)"),
                        "kind": got[0],
                        "new": got[1],
                        "name": name[:200],
                    }
                )

        # --- дефект 2: год
        if YEAR_BY_OPIS.search(prim):
            yr_state["по крайним датам описи"] += 1
            m = YEAR_IN_TEXT.search(text)
            if m:
                fixable_year.append(
                    {
                        "page_id": pid,
                        "arch": arch,
                        "fond": str(f.get("Фонд") or ""),
                        "opis": str(f.get("Опись") or ""),
                        "delo": str(f.get("Единица хранения") or ""),
                        "was": f.get("Год создания (нижняя)"),
                        "new": int(m.group(1)),
                        "name": name[:200],
                    }
                )
        elif f.get("Год создания (нижняя)"):
            yr_state["год есть, оговорки нет"] += 1
        else:
            yr_state["года нет"] += 1

    print(f"записей в выгрузке: {n}\n")
    print("ДЕФЕКТ 1 — МАСШТАБ, по каталогу целиком:")
    for k, c in sc_state.most_common():
        print(f"  {c:7d}  {k}  ({c * 100 // n} %)")
    print(f"\n  из эвристических масштаб НАПИСАН в заголовке: {len(fixable_scale)}")
    print(f"  по виду записи в тексте: {dict(scale_kinds)}")

    print("\n  эвристика по архивам (топ-10):")
    her = Counter(
        {a: c for (a, s), c in sc_by_arch.items() if s == "эвристика"}
    )
    for a, c in her.most_common(10):
        print(f"    {c:7d}  {a}")

    print("\nДЕФЕКТ 2 — ГОД, по каталогу целиком:")
    for k, c in yr_state.most_common():
        print(f"  {c:7d}  {k}")
    print(f"\n  из «по описи» год НАПИСАН в заголовке: {len(fixable_year)}")

    for name_, data in (
        ("fixable_scale.jsonl", fixable_scale),
        ("fixable_year.jsonl", fixable_year),
    ):
        p = OUT / name_
        with p.open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n→ {p} ({len(data)})")

    print("\nПРИМЕРЫ поправимого масштаба (до 12):")
    for r in fixable_scale[:12]:
        print(f"  [{r['kind']}] было 1:{r['was']} → 1:{r['new']} | {r['name'][:110]}")
    print("\nПРИМЕРЫ поправимого года (до 10):")
    for r in fixable_year[:10]:
        print(f"  было {r['was']} → {r['new']} | {r['name'][:110]}")


if __name__ == "__main__":
    main()
