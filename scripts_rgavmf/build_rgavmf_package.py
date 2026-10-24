"""Пакет каталога по РГАВМФ (Российский государственный архив Военно-Морского Флота).

ЧЕМ ЭТОТ ИСТОЧНИК ОСОБЫЙ. Масштаб, техника исполнения и ФОРМАТ ЛИСТА стоят прямо в
заголовке единицы хранения: «Карта Ярославской губернии. Печатная, в красках.
Масштаб 1 дюйм = 25 вёрст. Формат 365 х 410». Ни один другой наш источник так не
описывает — в ГПИБ ради тех же сведений пришлось скачивать сканы и читать картуши
зрением. Здесь они снимаются регуляркой на этапе обхода.

ДВА КЛАССА ЗАПИСЕЙ, И ВТОРОЙ ЗДЕСЬ ГЛАВНЫЙ ПО ОБЪЁМУ:
 1. `картография` — карты губерний, планы городов, сборные листы военно-топографической
    карты (ф. 3Л, описи 23 и 25);
 2. `пространственное описание` — делопроизводство Низового округа корабельных лесов
    (ф. 159, 33): освидетельствование деревьев, сведения о корабельных рощах, порубки,
    лесные дачи по губерниям. Это описание угодий конкретной территории, идущее в проекте
    наравне с картами, а НЕ картография: карты в таких делах может не быть вовсе.

⚠️ НАХОДКА ПРОГОНА 24.10. «Сборная военно-топографическая карта европейской части
России» ф. 3Л оп. 23 имеет масштаб 1 : 126 000 — это ТРЁХВЁРСТКА (3 версты в дюйме).
То есть РГАВМФ держит сборные листы того же издания, которое мы отдельно собирали
по всем пакетам (`scripts_review/sobrat_trehverstku.py`), и у здешних экземпляров
в заголовке проставлен формат листа 650 × 490.

⚠️ ЛОВУШКА ИСТОЧНИКА. Запрос «корабельных лесов» дал 1116 записей — больше всех
прочих вместе. Громадное их большинство к нашим четырём губерниям отношения не имеет
(Казанская, Симбирская, Нижегородская губернии — основной район лашманских лесов).
Территорию брать ТОЛЬКО из заголовка единицы хранения, не из слова запроса:
размер улова по запросу ничего не говорит о его пригодности
(память `feedback_fund-size-doesnt-predict-yield`).

Запуск:
    python -B scripts_rgavmf/build_rgavmf_package.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from false_carto import alien_hit, is_false_carto, not_a_place  # noqa: E402
from scope_rules import god_iz, klass, territories  # noqa: E402

SRC = ROOT / "output" / "rgavmf_20261024" / "rgavmf_items.jsonl"
OUT = ROOT / "output" / "rgavmf_package_20261024"

# Лесное делопроизводство: описание угодий территории, не картография
LESA = re.compile(
    r"корабельн\w+\s+(?:лес|рощ|дуб)|лашман|лесопильн|порубк|лесн\w+\s+дач"
    r"|освидетельствован\w+\s+дерев|о\s+(?:вырубке|рубке)\s+лес"
    r"|дубов\w+\s+рощ|о\s+лесах|сведения\s+о\s+лесах|лесоустройств", re.I)
# ⚠️ Делопроизводство О ЛЮДЯХ И ВЕЩАХ, а не об угодьях. Лесное слово в заголовке
# ещё не делает дело описанием территории: «О переводе корабельного мастера»,
# «О сотниках, обвиняемых в…», «Политдонесения», «Списки на выдачу денежного
# содержания» — всё это прошло в принятые на первом прогоне 24.10.
DELOPROIZVODSTVO = re.compile(
    r"^\s*(?:о|об)\s+(?:предполагаемом\s+)?(?:переводе|назначении|награждении"
    r"|увольнении|определении|производстве|командировании|отправлении|присылке"
    r"|выдаче|взыскании|сотник\w*|бывш)"
    r"|обвиняем\w+|политдонесен|денежн\w+\s+содержан"
    r"|списки\s+(?:и\s+ведомости\s+)?на\s+выдачу"
    r"|переписка\s+с[ои]?\s+\w*(?:военкомат|комиссией|конторой|управлением)"
    r"|послужн\w+\s+список|формулярн\w+\s+список"
    # сооружение флота, а не территория: док, эллинг, стапель, маяк, пристань
    r"|(?:сухо\w*|плавуч\w*|гидравлическ\w*|понтонн\w*)?\s*док\b|эллинг|стапел"
    r"|\bмаяк\b|\bмаяка\b|водопровод\w*\s+для\s+порт", re.I)
# ⚠️ ЧТО СЧИТАЕМ ОПИСАНИЕМ ТЕРРИТОРИИ (сужено 24.10 по разбору с пользователем).
# Класс `пространственное описание` в архиве флота нельзя ставить по общему правилу:
# подавляющая часть дел — переписка и учёт, где название губернии попало случайно
# («памятник на Смоленском кладбище в Петербурге», «переписка с Ярославской биржевой
# артелью», «формулярные списки рекрутов»). Описанием считаем только дела о ЗЕМЛЕ
# И УГОДЬЯХ: леса и рощи (LESA) либо явные описательные жанры ниже.
OPISANIE_TERR = re.compile(
    r"описани\w+\s+(?:\w+\s+){0,3}(?:губерн|уезд|намест|округ|дач|земл|город)"
    r"|(?:военно-)?статистическ\w+\s+обозрени|топографическ\w+\s+описани"
    r"|межеван|межев\w+\s+(?:книг|опис)|генеральн\w+\s+межеван"
    r"|экономическ\w+\s+примечани|описани\w+\s+границ"
    r"|сведени\w+\s+о\s+(?:земл|угодь|дач|рощ|лес)", re.I)

# ⚠️ УЕЗДНЫЕ ГОРОДА — добор территории, когда губерния в заголовке не названа
# (разбор 24.10). «План села Поречья» — Поречье уездный город Смоленской губернии,
# но гейт территорию не распознал и отправил запись в needs_human.
# ⚠️ КАЖДЫЙ ВАРИАНТ — С ГРАНИЦЕЙ СЛОВА `\b`. Без неё «Ельн» ловится внутри
# «кораб-ЕЛЬН-ых», и все 1116 дел о корабельных лесах получили Смоленскую губернию
# (поймано сразу после включения добора, 24.10). Тот же класс ошибки, что
# «Уфимск ⊂ КрасноУФИМСКий» в памяти проекта.
UEZDY = {
    "Калужская": r"\bБоровск|\bКозельск|\bМедын|\bМосальск|\bТарус[аы]\b|\bЖиздр"
                 r"|\bМещовск|\bПеремышл|\bЛихвин|\bМалоярославец|\bСухиничи",
    "Смоленская": r"\bВязьм|\bГжатск|\bДорогобуж|\bДуховщин|\bПоречь|\bРославл"
                  r"|\bЮхнов|\bЕльн|\bСыч[её]вк|\bБелый\s+уезд",
    "Ярославская": r"\bУглич|\bМышкин|\bПошехонь|\bМолог|\bРыбинск"
                   r"|\bРоманов-Борисоглебск|\bДанилов\w*\s+уезд"
                   r"|\bЛюбим\w*\s+уезд|\bРостов\w*\s+уезд",
    "Пермская": r"\bСоликамск|\bЧердын|\bКунгур|\bОханск|\bВерхотурь|\bИрбит"
                r"|\bШадринск|\bКрасноуфимск|\bКамышлов|\bЕкатеринбург|\bОсинск",
}
UEZDY = {g: re.compile(v, re.I) for g, v in UEZDY.items()}
# Трёхвёрстка: 1:126000 = 3 версты в дюйме
TRI_VERSTY = re.compile(r"1\s*:\s*126\s*000|3\s*верст\w*\s*в\s*дюйм", re.I)


def chitat(p: Path) -> list[dict]:
    out = []
    for ln in p.open(encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:  # noqa: BLE001, S112
                continue
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    prinyato: list[dict] = []
    nuzhen_chelovek: list[dict] = []
    otsev: list[dict] = []
    vidino: set[str] = set()

    for r in chitat(SRC):
        zag = (r.get("zagolovok") or "").strip()
        if not zag:
            continue
        klyuch = r.get("url") or f"{r.get('fond')}|{r.get('opis')}|{r.get('ed_hr')}"
        if klyuch in vidino:
            continue
        vidino.add(klyuch)

        lozh = is_false_carto(zag)
        gub = territories(zag)
        po_uezdu = ""
        if not gub:
            # губерния не названа — пробуем узнать её по уездному городу
            nashli = [g for g, rx in UEZDY.items() if rx.search(zag)]
            if len(nashli) == 1:
                gub, po_uezdu = nashli, "да"
        god, god_num = god_iz(zag, str(r.get("god") or ""), zag)
        lesnoe = bool(LESA.search(zag)) and not DELOPROIZVODSTVO.search(zag)
        kl = klass(zag, carto_ok=not lozh)
        # ⚠️ лесное дело — описание территории, даже если в заголовке есть «план»
        if lesnoe and kl != "картография":
            kl = "пространственное описание"
        if not kl and lesnoe:
            kl = "пространственное описание"
        if DELOPROIZVODSTVO.search(zag) and kl == "пространственное описание":
            kl = ""
        # ⚠️ сужение 24.10: описание территории — только о земле и угодьях
        if kl == "пространственное описание" and not (
                lesnoe or OPISANIE_TERR.search(zag)):
            kl = ""

        rec = {
            "arhiv": "РГАВМФ (Российский государственный архив Военно-Морского Флота)",
            "fond": r.get("fond", ""),
            "opis": r.get("opis", ""),
            "ed_hr": r.get("ed_hr", ""),
            "shifr": r.get("shifr", ""),
            "zagolovok": zag[:600],
            "klass": kl,
            "territoriya": "; ".join(gub),
            "territoriya_po_uezdu": po_uezdu,
            "god": god,
            # ⭐ снято прямо из заголовка единицы хранения, без чтения скана
            "masshtab": r.get("masshtab", ""),
            "format_lista": r.get("format_lista", ""),
            "tehnika": r.get("tehnika", ""),
            "trehverstka": "да" if TRI_VERSTY.search(zag) else "",
            "url": r.get("url", ""),
            "zapros": r.get("zapros", ""),
            "istochnik": "РГАВМФ",
        }

        # --- гейт ------------------------------------------------------------
        if lozh:
            rec["prichina"] = f"ложная картография: {lozh}"
            otsev.append(rec)
            continue
        if not kl:
            rec["prichina"] = "ни картография, ни пространственное описание"
            otsev.append(rec)
            continue
        if not gub:
            chuzhoe = alien_hit(zag)
            rec["prichina"] = (f"территория проекта не названа; чужая: {chuzhoe}"
                               if chuzhoe else "территория проекта в заголовке не названа")
            nuzhen_chelovek.append(rec)
            continue
        ne_mesto = not_a_place(zag)
        if ne_mesto:
            rec["prichina"] = f"совпадение не с местом: {ne_mesto}"
            nuzhen_chelovek.append(rec)
            continue
        if god_num and god_num > 1989:
            rec["prichina"] = f"год {god_num} позже границы проекта"
            otsev.append(rec)
            continue
        prinyato.append(rec)

    for imya, dannye in (("rgavmf_accepted", prinyato),
                         ("rgavmf_needs_human", nuzhen_chelovek),
                         ("rgavmf_scope_drops", otsev)):
        if not dannye:
            continue
        cols = list(dict.fromkeys(k for d in dannye for k in d))
        with (OUT / f"{imya}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(dannye)
        with (OUT / f"{imya}.jsonl").open("w", encoding="utf-8") as fh:
            for d in dannye:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"всего записей источника: {len(vidino)}")
    print(f"  принято:      {len(prinyato)}")
    print(f"  needs_human:  {len(nuzhen_chelovek)}")
    print(f"  отсев:        {len(otsev)}")
    print("\nпринято по губерниям:")
    sch = Counter(g for d in prinyato for g in d["territoriya"].split("; ") if g)
    for k, v in sch.most_common():
        print(f"  {v:>5}  {k}")
    print("\nпринято по классам:",
          dict(Counter(d["klass"] for d in prinyato).most_common()))
    print("принято по фондам:",
          dict(Counter(d["fond"] for d in prinyato).most_common(8)))
    po_u = sum(1 for d in prinyato if d.get("territoriya_po_uezdu"))
    print(f"\nтерритория добрана по уездному городу: {po_u}")
    print(f"с масштабом из заголовка: {sum(1 for d in prinyato if d['masshtab'])}")
    print(f"с форматом листа:         {sum(1 for d in prinyato if d['format_lista'])}")
    print(f"листов трёхвёрстки:       {sum(1 for d in prinyato if d['trehverstka'])}")
    print(f"с годом:                  {sum(1 for d in prinyato if d['god'])}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
