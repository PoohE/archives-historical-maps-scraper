"""Файл на просмотр по починенному пакету серийных карт: группировка по сериям.

Вход  — package_ready.jsonl (полный заголовок добыт) и package_still_human.jsonl.
Выход — ОБЗОР_пакет_серийных_карт.md: по сериям, с полным названием, держателем,
ссылкой на карточку, датами и тем, что надо решить человеку.

Ничего в Notion не пишет. Это материал для решения пользователя перед заливкой.

  python series_package_review.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

DIR = Path(
    r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\series_package_20261107"
)
OUT = DIR / "ОБЗОР_пакет_серийных_карт.md"


def load(name: str) -> list[dict]:
    p = DIR / name
    return [json.loads(ln) for ln in p.open(encoding="utf-8")] if p.exists() else []


def title(r: dict) -> str:
    return (r.get("zagolovok_polnyi") or r.get("zagolovok") or "(без названия)").strip()


def main() -> None:
    fix_stdout()
    ready, human = load("package_ready.jsonl"), load("package_still_human.jsonl")
    raw = load("series_package.jsonl")
    drops = [r for r in raw if r.get("gate") == "отсев"]
    if not ready and not human:
        print("!! нет починенных файлов — сначала series_package_repair.py")
        return

    by: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for r in ready:
        by[r["seriya"]].append(("готово", r))
    for r in human:
        by[r["seriya"]].append(("нужен человек", r))

    L: list[str] = []
    L.append("# Пакет серийных карт из библиотечного прогона — на просмотр\n")
    L.append("Прогон 07.11.2026 по названиям серий (а не по губерниям). "
             "**В Notion НЕ внесено ничего.** Это материал для решения.\n")
    L.append(f"- всего строк в исходном пакете: **{len(raw)}** "
             f"(из них отсев гейтом: {len(drops)})")
    L.append(f"- после дедупа по карточке и добора названий: **{len(ready) + len(human)}**")
    L.append(f"- с полным названием, пригодны к заливке: **{len(ready)}**")
    L.append(f"- требуют человека (название не добрано): **{len(human)}**\n")
    L.append("## Что было починено\n")
    L.append("1. **Обрезанные заголовки.** В исходном пакете у 230 из 402 записей вместо "
             "названия стоял сниппет выдачи с многоточием. Полные названия добраны "
             "с карточек: НЭБ-идентификатор `000199_000009_NNNNNNNNN` развёрнут в карточку "
             "РГБ `01NNNNNNNNN` (rusneb.ru отдаёт 403), Президентская библиотека и РГО — "
             "напрямую. РНБ через primo не берётся.")
    L.append("2. **Шаблонные губернии.** Поле «губернии серии» было подставлено из запроса "
             "(«Калужская; Смоленская; Ярославская; Пермская» стояло даже у Атласа Калужского "
             "наместничества). Теперь оставлены только те, что реально есть в названии; "
             "исходная подстановка сохранена в поле `gub_serii_shablon`.")
    L.append("3. **Дубли.** Одна карточка, попавшая в разные серии, склеена в одну строку "
             "с перечислением серий.\n")
    L.append("## Как читать\n")
    L.append("«готово» — название взято с каталожной карточки, запись можно заводить. "
             "«нужен человек» — карточка не отдала название, нужен ручной просмотр. "
             "Привязка листа к серии в обоих случаях требует сверки номенклатуры: гейт "
             "опознал серию по названию, территориального якоря в заголовке нет.\n")

    for ser in sorted(by, key=lambda s: (-len(by[s]), s)):
        rows = by[ser]
        ok = sum(1 for st, _ in rows if st == "готово")
        L.append(f"\n## {ser} — {len(rows)} записей ({ok} готовых)\n")
        L.append("| № | Статус | Название | Держатель | Годы | Губернии из названия | Карточка |")
        L.append("|---|---|---|---|---|---|---|")
        for i, (st, r) in enumerate(sorted(rows, key=lambda x: title(x[1])), 1):
            yrs = "–".join(x for x in (r.get("data_nachato"), r.get("data_okoncheno")) if x) or "—"
            gub = r.get("gub_serii") or "—"
            t = title(r).replace("|", "/")[:160]
            L.append(f"| {i} | {st} | {t} | {r['holder']} | {yrs} | {gub} | "
                     f"{r['record_url']} |")

    if drops:
        L.append(f"\n## Отсев гейтом — {len(drops)} записей (не предлагаются)\n")
        for r in drops[:40]:
            L.append(f"- {title(r)[:120]} — {r['holder']} — {(r.get('gate_reason') or '')[:90]}")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"готово: {OUT}")
    print(f"строк на просмотр: {len(ready) + len(human)} "
          f"(готовых {len(ready)}, нужен человек {len(human)}), отсев {len(drops)}")
    for ser in sorted(by, key=lambda s: -len(by[s])):
        ok = sum(1 for st, _ in by[ser] if st == "готово")
        print(f"  {len(by[ser]):>4} ({ok:>3} готовых)  {ser}")


if __name__ == "__main__":
    main()
