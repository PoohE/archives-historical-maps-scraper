"""Сборка итогового пакета ГАСО: три способа распознавания → единый набор + гейт отбора.

Входы (все три необязательны, берётся что есть):
  --vision    папка с JSONL от `extract_opis_vision.py` / `extract_opis_batch.py` (рукопись)
  --focr      JSONL от `parse_focr_opisi.py` (машинопись, прогон Винки)
  --textlayer JSONL от `parse_textlayer_opisi.py` (описи с текстовым слоем)

Гейт — по `ПРАВИЛА_ОТБОРА_источников.md` §1.1 и §1.1-бис: предмет подтверждается
картографическим признаком В ЗАГОЛОВКЕ, и к нему обязателен территориальный якорь.
Отсев НЕ выбрасывается: пишется отдельным файлом с мотивировкой (журнал решений).

Запуск:
    python -B scripts_gaso/build_gaso_package.py --out C:\\arch\\output\\gaso_package_20261013 \\
        --vision C:\\arch\\output\\gaso_vision_20261013 \\
        --focr C:\\arch\\output\\gaso_focr_parsed_20261013\\gaso_focr_records.jsonl \\
        --textlayer C:\\arch\\output\\gaso_textlayer_parsed_20261013\\gaso_textlayer_records.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_focr_opisi import OBJ, sign_of  # noqa: E402

OUT_FIELDS = ["fund", "opis", "n_delo", "zagolovok", "data_nachato", "data_okoncheno",
              "listov", "obyekt", "kartograficheskiy_priznak", "primechanie",
              "sposob", "page", "flags", "gate", "gate_reason"]

# Территориальный якорь (§1.1-бис): признак сам по себе предмета не доказывает.
# Якорь РАЗНОЙ силы: конкретный объект межевания (дача, пустошь, село, имение) — сильный,
# административная единица (уезд, волость, губерния) — слабый.
ANCHOR_STRONG = re.compile(
    r"деревн|дер\.\s*[А-ЯЁ]|\bд\.\s*[А-ЯЁ]|сельц|\bсел[аое]\b|селени|\bс\.\s*[А-ЯЁ]"
    r"|пустош|\bдач[аеиуы]|дачам|хутор|слобод|имени[ияе]\s+[А-ЯЁ]|им\.\s*[А-ЯЁ]"
    r"|мыз|погост|\bг\.\s*[А-ЯЁ]|город[аеу]?\b|сельск\w*\s+обществ",
    re.I)
ANCHOR_WEAK = re.compile(r"волост|уезд|губерни|округ|лесничеств", re.I)

# Признаки «сильные» — сами по себе подтверждают предмет (карта или данные к карте).
STRONG = {"план", "выкопировка", "чертёж", "карта", "межевая книга",
          "экономические примечания", "ведомость дачам", "владенная запись",
          "полевые записки", "съёмка", "оценка земель",
          # добавлено 13.10 по типологии актов межевания из предисловия ГАСО к ф. 814
          "описание границ", "полюбовная сказка", "список селений"}
# «Процессные» — межевание/размежевание/разверстание: это ДЕЙСТВИЕ, а не документ,
# и проходит только вместе с конкретным объектом и без финансовой начинки.
PROCESS = {"межевание"}

# Финансовое и кадровое делопроизводство: «о выдаче ссуды на хуторское землеустройство»
# к карте отношения не имеет, хотя слово «землеустройство» в заголовке есть.
MONEY = re.compile(
    r"ссуд|пособи|вознагражд|\bоплат|уплат|недоимк|жалован|оклад|смет|торг[аиов]|аренд"
    r"|покупк|продаж|залог|кредит|банк|расход|приход.*сумм|денежн", re.I)
STAFF = re.compile(r"перемещен|назначен|увольнен|личн\w*\s+состав|ваканси|прошени\w*\s+о\s+приня",
                   re.I)

NOT_CARTO = re.compile(r"план\w*\s+(?:работ|мероприят|счет|занят)", re.I)


def norm_sign(value: str | None, title: str) -> str:
    """Признак берём из заголовка своим словарём: у vision он свободный текст модели."""
    own = sign_of(title or "")
    if own != "нет":
        return own
    v = (value or "").strip().lower()
    return "нет" if v in ("", "нет", "none", "null") else v


def load_vision(folder: Path) -> list[dict]:
    rows = []
    for jsonl in sorted(folder.glob("*.jsonl")):
        stem = jsonl.stem
        fund, _, opis = stem.partition("_")
        opis = opis.split("_")[0] or "1"
        for ln in jsonl.open(encoding="utf-8"):
            if not ln.strip():
                continue
            page = json.loads(ln)
            for r in page.get("rows", []):
                title = (r.get("zagolovok") or "").strip()
                if not title:
                    continue
                rows.append({
                    "fund": fund, "opis": opis,
                    "n_delo": r.get("n_delo") or r.get("n_poryadok"),
                    "zagolovok": title,
                    "data_nachato": r.get("data_nachato"),
                    "data_okoncheno": r.get("data_okoncheno"),
                    "listov": r.get("listov"),
                    "obyekt": r.get("obyekt") or "; ".join(dict.fromkeys(OBJ.findall(title))) or None,
                    "kartograficheskiy_priznak": norm_sign(r.get("kartograficheskiy_priznak"), title),
                    "primechanie": r.get("primechanie"),
                    "sposob": "vision", "page": page.get("page"),
                    "flags": r.get("flags"),
                })
    return rows


def load_parsed(path: Path, sposob: str) -> list[dict]:
    rows = []
    for ln in path.open(encoding="utf-8"):
        if not ln.strip():
            continue
        r = json.loads(ln)
        title = (r.get("zagolovok") or "").strip()
        if not title:
            continue
        rows.append({**{k: r.get(k) for k in
                        ("fund", "opis", "n_delo", "zagolovok", "data_nachato",
                         "data_okoncheno", "listov", "obyekt", "primechanie", "flags")},
                     "kartograficheskiy_priznak": norm_sign(r.get("kartograficheskiy_priznak"), title),
                     "sposob": sposob, "page": None})
    return rows


def dedupe(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Снять повторы одной записи.

    Разворот подаётся двумя половинами, и запись, разрезанная переплётом, иногда
    выписывается дважды — на текущей странице и на следующей. Ключ: фонд+опись+номер
    дела+начало заголовка; при совпадении оставляем более длинный вариант заголовка.
    """
    best: dict[tuple, dict] = {}
    dupes: list[dict] = []
    for r in rows:
        title = re.sub(r"\W+", "", (r["zagolovok"] or "").lower())[:70]
        key = (r["fund"], r["opis"], (r.get("n_delo") or "").strip(), title)
        if not title:
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = r
        elif len(r["zagolovok"]) > len(prev["zagolovok"]):
            dupes.append(prev)
            best[key] = r
        else:
            dupes.append(r)
    return list(best.values()), dupes


def apply_gate(r: dict) -> tuple[str, str]:
    title = r["zagolovok"]
    sign = r["kartograficheskiy_priznak"]
    parts = {s.strip() for s in sign.split(",")} if sign != "нет" else set()
    strong_sign = parts & STRONG
    process_sign = parts & PROCESS

    if not parts:
        return "отсев", "предмет не подтверждён: картографического признака в заголовке нет"
    if NOT_CARTO.search(title):
        return "отсев", "«план работ/мероприятий» — документ учреждения, не карта"

    strong_anchor = bool(ANCHOR_STRONG.search(title) or ANCHOR_STRONG.search(r.get("obyekt") or ""))
    weak_anchor = bool(ANCHOR_WEAK.search(title) or ANCHOR_WEAK.search(r.get("obyekt") or ""))

    if strong_sign:
        if strong_anchor or weak_anchor:
            return "принято", f"признак «{', '.join(sorted(strong_sign))}» + территориальный якорь"
        return "needs_human", f"признак «{', '.join(sorted(strong_sign))}» есть, якоря нет"

    # остался только процессный признак (межевание/размежевание/разверстание)
    if MONEY.search(title):
        return "отсев", "финансовое делопроизводство (ссуда, покупка, аренда, смета)"
    if STAFF.search(title):
        return "отсев", "кадровое делопроизводство"
    if strong_anchor:
        return "принято", f"«{', '.join(sorted(process_sign))}» конкретного объекта"
    if weak_anchor:
        return "needs_human", f"«{', '.join(sorted(process_sign))}» без конкретного объекта"
    return "отсев", "процессный признак без территориальной привязки"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--vision", default="")
    ap.add_argument("--focr", default="")
    ap.add_argument("--textlayer", default="")
    args = ap.parse_args()

    rows: list[dict] = []
    if args.vision:
        rows += load_vision(Path(args.vision))
    if args.focr:
        rows += load_parsed(Path(args.focr), "focr")
    if args.textlayer:
        rows += load_parsed(Path(args.textlayer), "textlayer")

    rows, dupes = dedupe(rows)

    for r in rows:
        r["gate"], r["gate_reason"] = apply_gate(r)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, data: list[dict]) -> None:
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=OUT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps({k: r.get(k) for k in OUT_FIELDS}, ensure_ascii=False) + "\n")

    accepted = [r for r in rows if r["gate"] == "принято"]
    needs = [r for r in rows if r["gate"] == "needs_human"]
    dropped = [r for r in rows if r["gate"] == "отсев"]
    dump("gaso_all_records", rows)
    dump("gaso_accepted", accepted)
    dump("gaso_needs_human", needs)
    dump("gaso_scope_drops", dropped)

    by_fund: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_fund[r["fund"]][r["gate"]] += 1
    print(f"{'фонд':<8} {'всего':>6} {'принято':>8} {'ручная':>7} {'отсев':>7}  способ")
    sposob_by_fund = defaultdict(set)
    for r in rows:
        sposob_by_fund[r["fund"]].add(r["sposob"])
    for fund in sorted(by_fund, key=lambda x: -sum(by_fund[x].values())):
        c = by_fund[fund]
        print(f"{fund:<8} {sum(c.values()):>6} {c['принято']:>8} {c['needs_human']:>7} "
              f"{c['отсев']:>7}  {','.join(sorted(sposob_by_fund[fund]))}")

    if dupes:
        dump("gaso_duplicates", dupes)
        print(f"\nснято дублей (запись выписана дважды на соседних страницах): {len(dupes)}")
    print(f"\nВСЕГО записей: {len(rows)}")
    print(f"  принято:     {len(accepted)}")
    print(f"  needs_human: {len(needs)}")
    print(f"  отсев:       {len(dropped)}")
    signs = Counter(r["kartograficheskiy_priznak"] for r in accepted)
    print("\nпризнаки у принятых:")
    for k, v in signs.most_common(12):
        print(f"  {k:<30} {v}")
    print(f"\nпакет: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
