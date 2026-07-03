"""
Интерактивное уточнение параметров поиска перед запуском.

Спрашивает у пользователя:
  1. Губернии (исторические названия)
  2. Период (year_from, year_to)
  3. Детализация (только губерния / губерния + уезды / конкретные уезды)

Возвращает готовый список запросов для catalog_search.py.
"""
import sys
from territories import GUBERNIA_QUERIES, UYEZD_QUERIES, expand_query, get_queries

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")


def ask(prompt: str) -> str:
    print(f"\n{prompt}")
    return input("→ ").strip()


def parse_year(s: str, default: int) -> int:
    """Извлекает год из строки типа '1760', 'XVIII в.', 'до 1850'."""
    import re
    m = re.search(r"\d{4}", s)
    if m:
        return int(m.group())
    # Век → диапазон
    century = re.search(r"(X{0,2}I{0,3}V?I*)\s*в", s, re.I)
    if century:
        roman = {"XVIII": 1700, "XIX": 1800, "XX": 1900,
                 "XVII": 1600, "XVI": 1500}
        for r, y in roman.items():
            if r.lower() in s.lower():
                return y if default < y + 100 else y + 99
    return default


def clarify() -> dict:
    """
    Задаёт три вопроса и возвращает параметры поиска:
    {
        "territories": ["Калужская губерния", "Козельский уезд", ...],
        "year_from": 1760,
        "year_to": 1860,
        "label": "Калужская 1760–1860",
    }
    """
    known = list(GUBERNIA_QUERIES.keys())  # ['калужская', 'пермская', ...]

    # ── Вопрос 1: губернии ───────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("УТОЧНЕНИЕ ПАРАМЕТРОВ ПОИСКА")
    print("═" * 60)
    print(f"\nДоступные губернии в справочнике: {', '.join(g.title() for g in known)}")
    print("Если нужна другая губерния — она будет добавлена вручную.")

    gub_raw = ask(
        "1. Какие губернии входят в интересующую территорию?\n"
        "   (перечисли через запятую, как назывались в исторический период)"
    )

    selected_gubs: list[str] = []
    unknown_gubs: list[str] = []
    for part in gub_raw.replace(";", ",").split(","):
        name = part.strip().lower().rstrip("аяой")  # калужская → калуж
        found = next((k for k in known if name in k or k in name), None)
        if found:
            selected_gubs.append(found)
        else:
            unknown_gubs.append(part.strip())

    if unknown_gubs:
        print(f"\n  ⚠ Не найдены в справочнике: {', '.join(unknown_gubs)}")
        print("  Эти губернии будут пропущены.")
        print("  Чтобы добавить — дополни modules/territories.py и Notion «Административные единицы».")

    if not selected_gubs:
        print("\n  Нет совпадений. Используем все 4 губернии гранта.")
        selected_gubs = known

    # ── Вопрос 2: период ────────────────────────────────────────────────────
    period_raw = ask(
        "2. На какой исторический период искать?\n"
        "   (например: 1750–1850, XVIII в., до 1917)"
    )
    # Разбираем диапазон
    import re
    years = re.findall(r"\d{4}", period_raw)
    if len(years) >= 2:
        year_from, year_to = int(years[0]), int(years[1])
    elif len(years) == 1:
        y = int(years[0])
        if "до" in period_raw.lower() or "по" in period_raw.lower():
            year_from, year_to = 1700, y
        else:
            year_from, year_to = y, y + 50
    else:
        year_from = parse_year(period_raw, 1750)
        year_to   = parse_year(period_raw, 1917)

    # ── Вопрос 3: детализация ───────────────────────────────────────────────
    detail_raw = ask(
        "3. Детализация поиска:\n"
        "   [1] Только по губернии в целом (быстро)\n"
        "   [2] Губерния + все уезды (полнее, дольше)\n"
        "   [3] Конкретные уезды (укажу сам)"
    ).strip()

    territories: list[str] = []

    if detail_raw == "3":
        uyezd_raw = ask("   Перечисли уезды через запятую:")
        territories = [u.strip() for u in uyezd_raw.split(",") if u.strip()]
    elif detail_raw == "2":
        for gub in selected_gubs:
            territories.extend(GUBERNIA_QUERIES[gub])
            territories.extend(UYEZD_QUERIES.get(gub, ()))
    else:  # "1" или что угодно
        for gub in selected_gubs:
            territories.extend(GUBERNIA_QUERIES[gub])

    # ── Сводка ──────────────────────────────────────────────────────────────
    label = f"{', '.join(g.title() for g in selected_gubs)} {year_from}–{year_to}"
    print("\n" + "─" * 60)
    print("ПАРАМЕТРЫ ПОИСКА:")
    print(f"  Губернии:    {', '.join(g.title() for g in selected_gubs)}")
    print(f"  Период:      {year_from}–{year_to}")
    print(f"  Территорий:  {len(territories)} запросов")
    if len(territories) <= 20:
        for t in territories:
            print(f"    • {t}")
    else:
        for t in territories[:5]:
            print(f"    • {t}")
        print(f"    ... ещё {len(territories) - 5}")
    print("─" * 60)

    confirm = ask("Всё верно? [Enter — продолжить / любой текст — отменить]")
    if confirm:
        print("Отменено.")
        sys.exit(0)

    return {
        "territories": territories,
        "year_from":   year_from,
        "year_to":     year_to,
        "label":       label,
    }


if __name__ == "__main__":
    params = clarify()
    print(f"\nПараметры для скрипта: {params}")
