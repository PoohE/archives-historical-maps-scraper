"""Сборка пакета на внесение: все поля чек-листа, без записи в Notion.

Вход:
  output/work_2026-11-08/harvested.jsonl       — добор 08.11 (РГБ, ПБ, КП)
  output/work_2026-11-08/harvested_neb.jsonl   — добор НЭБ через scrape.do (если есть)
  данные/найденные_источники.sqlite            — губернии и флаг скоупа по ключу

Выход (в output/package_2026-11-08/):
  package_A_scope.jsonl    — территория названа, серия наша → кандидаты на внесение
  package_B_sheets.jsonl   — серия наша/частично, территория по заголовку НЕ определяется
                             (лист межгубернской серии) → нужен сборный лист
  package_C_foreign.jsonl  — серия чужой территории → отклонён, в Notion не вносится
  package_D_blocked.jsonl  — карточка не добрана (РГО лежит)
  ОБЗОР_пакет_на_внесение.md — разбор по семи пунктам чек-листа предзаливки

Ничего не пишет в Notion. Это материал для решения пользователя.

  python package_full_fields.py
"""

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from series_package_enrich import parse_card  # noqa: E402
from series_registry import HOLDERS, inherit_for, scope_for, series_nums  # noqa: E402
from territory_gate import classify as terr_classify  # noqa: E402
from territory_gate import our_gubernii  # noqa: E402
from territory_gate import rubric_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "work_2026-11-08"
OUT = ROOT / "output" / "package_2026-11-08"
DB = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\найденные_источники.sqlite"
)

PROGON = "Claude, прогон 08.11.2026"

GUB2REG = {
    "Калужская": "Калужская область",
    "Смоленская": "Смоленская область",
    "Ярославская": "Ярославская область",
    "Пермская": "Пермский край (частью — Свердловская обл., Удмуртия, Башкортостан)",
}

# Тип источника по номеру серии (классификатор каталога, см. чек-лист п. 5).
TYPE_BY_SERIES = {
    "1": "Text — писцовая книга (не карта)",
    "знаки": "Text — таблица условных знаков / инструкция",
    "2": "A2 — обзорная карта / атлас",
    "4": "A2 — обзорная карта / атлас",
    "5": "A2 — обзорная карта / атлас",
    "5а": "A2 — обзорная карта / атлас",
    "3": "A3 — межевой план",
    "11": "A3 — межевой план (топографо-межевая съёмка)",
    "6": "A4 — военно-топографическая карта",
    "7": "A4 — военно-топографическая карта",
    "8": "A4 — военно-топографическая карта",
    "9": "A4 — военно-топографическая карта",
    "10": "A4 — военно-топографическая карта",
    "12": "A4 — военно-топографическая карта",
    "13": "A4 — военно-топографическая карта",
    "14": "A4 — военно-топографическая карта",
    "15": "A4 — военно-топографическая карта",
    "16": "A4 — военно-топографическая карта",
    "17": "A4 — военно-топографическая карта",
    "18": "A4 — военно-топографическая карта",
}

TAILS = re.compile(
    r"\s*(?:- Search RSL|\| Президентская библиотека.*|\| НЭБ.*|— читать.*|— смотреть.*)$",
    re.I,
)
# Ложные «губернские» вхождения: прилагательное относится не к губернии.
FALSE_GUB = re.compile(
    r"(Смоленск|Калужск|Ярославск|Пермск)\w*\s+"
    r"(ямская|слобода|улица|застава|дорога|шоссе|тракт|железная|уезд\w*\s+[А-ЯЁ])",
    re.I,
)


def load(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in p.open(encoding="utf-8") if ln.strip()] if p.exists() else []


BAD_TITLE = re.compile(
    r"^(?:Масштаб|Текст|Загл|\d|[А-ЯЁ][а-яё]+\s*:\s*(?:Тип|Изд|Воен|Литогр))",
)


def _is_title(s: str) -> bool:
    """Похоже ли на заглавие, а не на масштаб, выходные данные или годы.

    ⚠️ Поймано 08.11.2026: слепой выбор второго куска после «. - » давал названия
    «Масштаб = 1 дюйм : 10 верст…», «1846—1934», «Санктпетербург : Тип. Акад. наук, 1785».
    """
    s = s.strip()
    return bool(s) and not BAD_TITLE.match(s) and len(re.sub(r"[^А-Яа-яЁёA-Za-z]", "", s)) >= 6


def short_title(full: str) -> str:
    """Короткое название: собственно заглавие, без территории-рубрики и аппарата.

    Формат карточки РГБ: «<Территория-рубрика>. - <Заглавие>: [Карты] : <подзаголовок>
    / <ответственность>. - <масштаб>. - <выходные данные>». Берём заглавие,
    а не рубрику — иначе название дублирует территорию (поймано 08.11.2026).
    """
    t = TAILS.sub("", (full or "").strip())
    parts = re.split(r"\.\s+-\s+", t)
    if len(parts) > 1 and len(parts[0]) < 60 and _is_title(parts[1]):
        t = parts[1]
    t = t.split(" / ")[0]
    t = re.split(r"\s*:\s*\[(?:Карты|Карта|Текст|Атлас)\]", t)[0]
    t = re.split(r"\s+[-—]\s+(?:Масштаб|1\s*:)", t)[0]
    t = t.replace("[", "").replace("]", "").strip(" .,;:—-")
    return re.sub(r"\s{2,}", " ", t)[:180] or TAILS.sub("", (full or "").strip())[:180]


def holder_of(key: str) -> str:
    return (key or ":").split(":", 1)[0]


def build(row: dict, st: dict | None) -> dict:
    """Собрать поля чек-листа для одной записи."""
    full = (row.get("zagolovok_polnyi") or row.get("zagolovok") or "").strip()
    full = TAILS.sub("", full)
    holder = holder_of(row.get("key", ""))
    nums = series_nums(row.get("seriya", ""))
    inh, srcs, bans = inherit_for(row.get("seriya", ""))
    card = parse_card(full) if full else {}

    f: dict = {}
    f["Название источника"] = short_title(full)
    f["Описание"] = full
    f["Ссылка на источник"] = row.get("url", "")

    # держатель: у НЭБ настоящий фондодержатель стоит в карточке
    arch = HOLDERS.get(holder, {}).get("archive", "")
    place = HOLDERS.get(holder, {}).get("place", "")
    if holder in ("НЭБ", "КП"):
        real = row.get("hranitel") or (row.get("polya") or {}).get("Библиотека") or ""
        if real:
            arch, place = real, real
    f["Архив хранения"] = arch
    f["Место хранения"] = place
    f["Библиотечный шифр"] = row.get("shelf") or card.get("Библиотечный шифр") or ""

    f["Тип источника"] = "; ".join(
        dict.fromkeys(TYPE_BY_SERIES.get(n, "") for n in nums if TYPE_BY_SERIES.get(n))
    )
    f["Язык"] = "Русский"
    f["Статус приёмки"] = "кандидат"
    f["Статус доступа"] = (
        "Цифровая копия в источнике" if row.get("url") else "Только метаданные"
    )
    f["Серия / массив"] = row.get("seriya", "")
    f["Автор внесения / Дата внесения"] = PROGON

    # масштаб и прочее: карточка побеждает, затем наследование
    inherited: list[str] = []
    for k, v in list(card.items()):
        f[k] = v
    for k, v in inh.items():
        if not f.get(k):
            f[k] = v
            inherited.append(k)
    if row.get("scale") and not card.get("Масштаб (знаменатель)"):
        f["Масштаб (знаменатель)"] = row["scale"]
        if row.get("scale_ctx"):
            f["Оригинальный масштаб"] = row["scale_ctx"]
        if "Масштаб (знаменатель)" in inherited:
            inherited.remove("Масштаб (знаменатель)")
    if row.get("god_text") and not f.get("Год создания (нижняя)"):
        y = re.search(r"(1[5-9]\d\d|20\d\d)", row["god_text"])
        if y:
            f["Год создания (нижняя)"] = int(y.group(1))

    # территория — своим гейтом по полному заголовку (см. territory_gate.py)
    verdict, why = terr_classify(full)
    if verdict == 'нет':
        rv, rwhy = rubric_verdict(full)
        if rv in ('наша', 'чужая'):
            verdict, why = rv, rwhy
        elif rv == 'учреждение':
            why = why + '; ' + rwhy
    gub_list = our_gubernii(full)
    gub = "; ".join(gub_list)
    store_gub = (st or {}).get("gubernii") or ""
    if gub:
        f["Охватываемая территория"] = gub
        f["Современные регионы"] = "; ".join(GUB2REG.get(g, g) for g in gub_list)
        f["Административный уровень"] = "⚠️ требует решения: лист межгубернской серии"
    else:
        f["Охватываемая территория"] = ""
        f["Современные регионы"] = ""
        f["Административный уровень"] = ""

    note = []
    if inherited:
        note.append(
            "Часть полей взята ОТ СЕРИИ, не сверена по листу: "
            + ", ".join(inherited)
            + ". Основание — "
            + " | ".join(srcs)
        )
    if bans:
        note.append("Наследование запрещено: " + " | ".join(bans))
    note.append(f"Территориальный гейт: {verdict} — {why}")
    if store_gub and not gub:
        note.append(
            f"⚠️ Расхождение с флагом базы: там стоит «{store_gub}», наш гейт территорию "
            "не подтвердил (вероятно омоним или уезд землемера) — проверить человеком"
        )
    if gub and store_gub and set(x.strip() for x in store_gub.split(";")) != set(gub_list):
        note.append(
            f"⚠️ Расхождение с флагом базы: там «{store_gub}», у нас «{gub}» — проверить"
        )
    if note:
        f["Примечания по оцифровке"] = " ".join(note)

    return {
        "key": row["key"],
        "terr_verdict": verdict,
        "holder": holder,
        "seriya": row.get("seriya", ""),
        "series_nums": nums,
        "scope": scope_for(row.get("seriya", "")),
        "url": row.get("url", ""),
        "status_dobora": row.get("status", ""),
        "notion_fields": f,
        "_inherited": inherited,
    }


REQUIRED = [
    "Название источника",
    "Описание",
    "Архив хранения",
    "Тип источника",
    "DC Type",
    "Язык",
    "Место хранения",
    "Статус приёмки",
    "Статус доступа",
    "Серия / массив",
    "Автор внесения / Дата внесения",
    "Ссылка на источник",
]


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)

    rows = {r["key"]: r for r in load(WORK / "harvested.jsonl")}
    neb = load(WORK / "harvested_neb.jsonl")
    for r in neb:
        if r.get("status") == "добрано":
            rows[r["key"]] = r
    print(f"строк всего: {len(rows)} (из них добор НЭБ: {sum(1 for r in neb if r.get('status') == 'добрано')})")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    st = {
        r["klyuch"]: dict(r)
        for r in con.execute("select klyuch, gubernii, v_skoupe, masshtab, shifr from istochniki")
    }
    con.close()

    groups: dict[str, list[dict]] = defaultdict(list)
    for key, row in rows.items():
        if row.get("status") != "добрано":
            groups["D"].append(build(row, st.get(key)))
            continue
        rec = build(row, st.get(key))
        y = rec["notion_fields"].get("Год создания (нижняя)")
        if isinstance(y, int) and y > 1980:
            rec["notion_fields"]["Статус приёмки"] = "отклонён — позже 1980 г."
            groups["E"].append(rec)
            continue
        v = rec["terr_verdict"]
        if v == "наша":
            groups["A"].append(rec)
        elif v == "чужая" or rec["scope"] == "чужая":
            rec["notion_fields"]["Статус приёмки"] = "отклонён — чужая территория"
            groups["C"].append(rec)
        elif v == "общая":
            rec["notion_fields"]["Статус приёмки"] = (
                "отклонён — обзорная карта без губернского уровня"
            )
            groups["F"].append(rec)
        else:
            groups["B"].append(rec)

    names = {
        "A": "package_A_scope.jsonl",
        "B": "package_B_sheets.jsonl",
        "C": "package_C_foreign.jsonl",
        "D": "package_D_blocked.jsonl",
        "E": "package_E_post1980.jsonl",
        "F": "package_F_general.jsonl",
    }
    for g, fn in names.items():
        with (OUT / fn).open("w", encoding="utf-8") as fh:
            for rec in groups[g]:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  {g}: {len(groups[g]):>5} → {fn}")

    # ---- аудит заполненности по группе A
    rep: list[str] = []
    rep.append("# Пакет на внесение в каталог — разбор перед заливкой\n")
    rep.append(
        "Собран `package_full_fields.py` 08.11.2026. **В Notion ничего не внесено.**\n"
        "Разбор по формату чек-листа предзаливки (`docs/archive/ЧЕКЛИСТ_ПРЕДЗАЛИВКИ_полей.md`,\n"
        "раздел «Формат разбора пакета», семь пунктов).\n"
    )

    rep.append("## 1. Арифметика пакета\n")
    rep.append("| Группа | Что это | Записей |")
    rep.append("|---|---|---|")
    rep.append(f"| **A** | территория названа в заголовке, серия наша → кандидаты на внесение | **{len(groups['A'])}** |")
    rep.append(f"| **B** | лист межгубернской серии, территория по заголовку не определяется | {len(groups['B'])} |")
    rep.append(f"| **C** | серия чужой территории (Кавказ, Туркестан, Закаспий, Азиатская Россия, Западная Россия) → отклонён | {len(groups['C'])} |")
    rep.append(f"| **D** | карточка не добрана (источник недоступен) | {len(groups['D'])} |")
    rep.append(f"| **E** | издание позже 1980 г. → вне охвата каталога для библиотек | {len(groups['E'])} |")
    rep.append(f"| **F** | обзорная карта России / Европейской России / мира → отклонён (нет губернского уровня) | {len(groups['F'])} |")
    tot = sum(len(v) for v in groups.values())
    rep.append(f"| | **итого** | **{tot}** |")
    rep.append(
        f"\nТретье независимое число: в рабочем списке `work.jsonl` было **{len(rows)}** строк "
        f"после дедупа и отсева тех, что уже в каталоге; сумма групп — **{tot}**. "
        f"{'Сходится.' if tot == len(rows) else '⚠️ НЕ СХОДИТСЯ — разобраться.'}\n"
    )

    rep.append("## 2. Дедуп по ключу\n")
    dup = [k for k, n in Counter(r["key"] for v in groups.values() for r in v).items() if n > 1]
    rep.append(f"Ключ — `держатель:идентификатор`. Дублей: **{len(dup)}**.\n")

    rep.append("## 3. Дедуп и аномалии по тексту заголовка\n")
    tc = Counter(r["notion_fields"]["Описание"] for r in groups["A"] + groups["B"])
    same = [(t, n) for t, n in tc.items() if n > 1]
    rep.append(
        f"Одинаковых заголовков при разных ключах: **{len(same)}** "
        f"(для серийных листов это нормально — источник режет заголовок в списочной выдаче).\n"
    )
    for t, n in sorted(same, key=lambda x: -x[1])[:10]:
        rep.append(f"- {n}× «{t[:110]}»")
    rep.append("")

    rep.append("## 4. Заполненность обязательных полей (группа A)\n")
    rep.append("| Поле | Заполнено | Пусто | Допустимо ли пусто |")
    rep.append("|---|---|---|---|")
    A = groups["A"]
    for k in REQUIRED + [
        "Масштаб (знаменатель)",
        "Оригинальный масштаб",
        "Автор / составитель",
        "Библиотечный шифр",
        "Охватываемая территория",
        "Административный уровень",
        "Год создания (нижняя)",
    ]:
        f = sum(1 for r in A if r["notion_fields"].get(k) not in (None, "", []))
        ok = {
            "Масштаб (знаменатель)": "да — где серия с разными масштабами",
            "Оригинальный масштаб": "да — там же",
            "Автор / составитель": "да — не угадывать",
            "Библиотечный шифр": "да — библиотека могла не отдать",
            "Год создания (нижняя)": "да — если не стоит в карточке",
            "Административный уровень": "⚠️ НЕТ — нужно решение по уровню листа серии",
        }.get(k, "нет — обязательное")
        rep.append(f"| {k} | {f} | {len(A) - f} | {ok} |")
    rep.append("")

    rep.append("## 5. Тип источника и DC Type по пакету (группа A)\n")
    rep.append("| Тип источника | DC Type | Записей |")
    rep.append("|---|---|---|")
    for (t, d), n in Counter(
        (r["notion_fields"]["Тип источника"], r["notion_fields"].get("DC Type", "—")) for r in A
    ).most_common():
        rep.append(f"| {t or '(пусто)'} | {d} | {n} |")
    rep.append("")

    rep.append("## 6. Одна карточка целиком, поле-в-поле\n")
    if A:
        sample = max(A, key=lambda r: len(r["notion_fields"]))
        rep.append(f"Пример — `{sample['key']}`, {sample['url']}\n")
        rep.append("| Поле Notion | Значение |")
        rep.append("|---|---|")
        for k, v in sample["notion_fields"].items():
            rep.append(f"| {k} | {str(v)[:400]} |")
        rep.append("")

    rep.append("## 7. Записи вне базовой территориально-временной модели\n")
    rep.append(
        "**Группа B — главный вопрос пакета.** Это листы межгубернских серий: территория "
        "в заголовке не названа («Ряд XIII лист 10», «Лист 44»), а значит губернию нельзя "
        "определить по тексту — только по сборному листу серии. Отбрасывать их нельзя "
        "(это наши серии), вносить с пустой территорией тоже. Разбивка по сериям:\n"
    )
    rep.append("| Серия | Записей в B | Что нужно, чтобы решить |")
    rep.append("|---|---|---|")
    needs = {
        "10": "сборный лист трёхвёрстки (ряд/лист → губерния)",
        "13": "сборный лист Стрельбицкого (номера листов → губернии)",
        "8": "сборный лист Шуберта (59 листов + 3 клапана)",
        "5а": "сборный лист Столистовой (110 листов)",
        "7": "перечень губернских комплектов КВТ",
        "11": "перечень губерний съёмки Менде (8 губерний)",
        "3": "привязка плана к уезду по описи",
        "17": "номенклатура 1:100 000 (N-36, N-37, O-40…)",
        "15": "сборный лист Омского ВО",
        "1": "привязка писцовой книги к уезду",
        "знаки": "не карта — территория не нужна",
    }
    for n, cnt in Counter(
        num for r in groups["B"] for num in r["series_nums"]
    ).most_common():
        rep.append(f"| серия {n} | {cnt} | {needs.get(n, 'сборный лист / номенклатура серии')} |")
    rep.append("")
    rep.append(
        "**Группа D — недобранное.** РГО (`elib.rgo.ru`) не отвечает даже через российские "
        "прокси (HTTP 502 через scrape.do 08.11.2026) — сайт лежит, а не блокирует. "
        "Возвращаться, когда поднимется.\n"
    )

    (OUT / "ОБЗОР_пакет_на_внесение.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"\nотчёт: {OUT / 'ОБЗОР_пакет_на_внесение.md'}")


if __name__ == "__main__":
    main()
