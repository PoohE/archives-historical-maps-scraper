"""Поиск НЕУЧТЁННЫХ серийных массивов по нашей же базе найденных источников.

Вопрос пользователя 08.11.2026: «можно ли на основе наших скачанных материалов
по количеству листов найти ещё серийные массивы, которые мы не учли?»

Три независимых признака серийности, считаются по 39 637 записям
`данные/найденные_источники.sqlite` — БЕЗ интернета:

  1. ПОВТОР ЗАГОЛОВКА. Нормализуем заголовок (снимаем номера листов, годы,
     номера рядов) и группируем. Один и тот же «корень» у ≥3 записей с РАЗНЫМИ
     номерами — признак многолистного издания.
  2. ЧИСЛО ЛИСТОВ В ОПИСАНИИ. Поле `listy` и текст карточки: «59 л.», «110 отд. л.»,
     «1 к. (45 л.)» — издание, объявляющее десятки листов, почти всегда серия.
  3. НОМЕНКЛАТУРА В ЗАГОЛОВКЕ: «Ряд XIII лист 10», «Лист 44», «N-37-87», «XXIV–9».

Выход: output/series_candidates_store/ОБЗОР_кандидаты_серий_из_базы.md — только
то, что НЕ отнесено ни к одной из серий 1–18 (поле `seriya` пустое или без номера).

  python find_series_in_store.py
"""

import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

DB = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\найденные_источники.sqlite"
)
OUT = Path(__file__).resolve().parents[1] / "output" / "series_candidates_store"

# Снимаем всё, что отличает ЛИСТ от ИЗДАНИЯ.
STRIP = [
    (re.compile(r"\[?\d{4}(?:\s*[—–-]\s*\d{4})?\]?"), " "),          # годы
    (re.compile(r"ряд\s+[IVXLC]+", re.I), " "),                       # ряд XIII
    (re.compile(r"лист(?:ы)?\s*[№N]?\s*[\dIVXLC,\s–—-]+", re.I), " "),  # лист 44
    (re.compile(r"\b[NOPQ]-\d{1,2}(?:-[\dIVXLC-]+)?\b"), " "),        # N-37-87
    (re.compile(r"\b[IVXLC]+\s*[–—-]\s*\d+\b"), " "),                 # XXIV–9
    (re.compile(r"\b\d{3,6}\b"), " "),                                # внутренние номера
    (re.compile(r"1\s*[:：]\s*\d[\d\s\u00a0]*"), " "),                 # масштаб
    (re.compile(r"[\[\]()«»„“”\"'.,;:/\\]"), " "),
]
SHEETS = re.compile(r"(\d{2,4})\s*(?:отд\.\s*)?л(?:\.|истов|иста)\b", re.I)
NOMEN = re.compile(
    r"(ряд\s+[IVXLC]+|\bлист\s*\d+|\b[NOPQ]-\d{1,2}-\d+|\b[IVXLC]{1,6}\s*[–—-]\s*\d+)",
    re.I,
)
KNOWN = re.compile(r"серия\s+\d", re.I)


def norm(t: str) -> str:
    s = (t or "").lower()
    for pat, rep in STRIP:
        s = pat.sub(rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in con.execute(
            "select klyuch, derzhatel, nazvanie, nazvanie_polnoe, seriya, listy, "
            "god_ot, gubernii, url from istochniki"
        )
    ]
    con.close()
    print(f"записей в базе: {len(rows)}")

    unknown = [r for r in rows if not KNOWN.search(r.get("seriya") or "")]
    print(f"не отнесено ни к одной серии 1–18: {len(unknown)}")

    # --- признак 1: повтор нормализованного заголовка
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in unknown:
        t = (r.get("nazvanie_polnoe") or r.get("nazvanie") or "").strip()
        n = norm(t)
        if len(n) >= 18:
            groups[n].append(r)
    repeats = sorted(
        ((k, v) for k, v in groups.items() if len(v) >= 3),
        key=lambda x: -len(x[1]),
    )

    # --- признак 2: объявленное число листов
    many: list[tuple[int, dict]] = []
    for r in unknown:
        t = (r.get("nazvanie_polnoe") or "") + " " + (r.get("listy") or "")
        best = 0
        for m in SHEETS.finditer(t):
            best = max(best, int(m.group(1)))
        if best >= 20:
            many.append((best, r))
    many.sort(key=lambda x: -x[0])

    # --- признак 3: номенклатура в заголовке
    nomen = [
        r
        for r in unknown
        if NOMEN.search((r.get("nazvanie_polnoe") or r.get("nazvanie") or ""))
    ]

    rep: list[str] = []
    rep.append("# Кандидаты в серийные массивы — из НАШЕЙ базы, без интернета\n")
    rep.append(
        f"Собрано `find_series_in_store.py` по {len(rows)} записям "
        f"`найденные_источники.sqlite`. Отобраны только записи, **не отнесённые** "
        f"ни к одной из серий 1–18 ({len(unknown)} шт.).\n"
    )

    rep.append("## 1. Повтор заголовка при разных номерах листов\n")
    rep.append(
        "Заголовок нормализован: сняты годы, номера листов и рядов, номенклатура, "
        "масштаб. Если один «корень» встречается у трёх и более записей — перед нами "
        "многолистное издание, а не отдельная карта.\n"
    )
    rep.append("| Записей | Держатели | Годы | Нормализованный корень заголовка |")
    rep.append("|---|---|---|---|")
    for k, v in repeats[:40]:
        hold = ", ".join(sorted({x["derzhatel"] or "?" for x in v}))
        yy = sorted({str(x["god_ot"]) for x in v if x.get("god_ot")})
        yr = f"{yy[0]}–{yy[-1]}" if len(yy) > 1 else (yy[0] if yy else "—")
        rep.append(f"| {len(v)} | {hold[:28]} | {yr} | {k[:95]} |")
    rep.append("")

    rep.append("## 2. Издания, объявляющие 20 и более листов\n")
    rep.append("| Листов | Держатель | Заголовок |")
    rep.append("|---|---|---|")
    seen: set[str] = set()
    for n, r in many[:40]:
        t = (r.get("nazvanie_polnoe") or r.get("nazvanie") or "")[:110]
        if t in seen:
            continue
        seen.add(t)
        rep.append(f"| **{n}** | {r['derzhatel']} | {t} |")
    rep.append("")

    rep.append("## 3. Номенклатура листа прямо в заголовке\n")
    rep.append(f"Таких записей: **{len(nomen)}**. Распределение по держателям: ")
    rep.append(
        ", ".join(f"{k} — {v}" for k, v in Counter(r["derzhatel"] for r in nomen).most_common())
    )
    rep.append("\n| Держатель | Заголовок |")
    rep.append("|---|---|")
    for r in nomen[:30]:
        rep.append(
            f"| {r['derzhatel']} | {(r.get('nazvanie_polnoe') or r['nazvanie'])[:110]} |"
        )
    rep.append("")

    path = OUT / "ОБЗОР_кандидаты_серий_из_базы.md"
    path.write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"повторов заголовка (≥3): {len(repeats)}")
    print(f"изданий с 20+ листами: {len(many)}")
    print(f"с номенклатурой в заголовке: {len(nomen)}")
    print(f"отчёт: {path}")


if __name__ == "__main__":
    main()
