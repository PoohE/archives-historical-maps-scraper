"""
Разбор результатов прогона поиска ПЕРЕД заливкой в Notion.

Детерминированное оффлайн-ядро (без сети): фильтр по критериям РНФ →
схлопывание дублей внутри прогона → диф против уже занесённого в Notion →
три корзины: авто-оставить / на ручную проверку / отсеять (с причиной).

Сетевую часть (выгрузку существующих URL «Каталога» из Notion) делает скил
review-run и передаёт сюда файлом --existing. Так скрипт остаётся оффлайн и
тестируемым — как notion_export.py.

Запуск:
  python scripts/run_review.py output/<run>            # без диффа против Notion
  python scripts/run_review.py output/<run> --existing notion_existing.json
  python scripts/run_review.py output/<run> --out output/<run>/review_run

Вход:  <run>/records_full.jsonl  (entry: source/territory/keyword/record)
Выход в <out>/:
  review.csv            — корзина «на ручную проверку» (формат для review.py)
  accepted_records.jsonl— корзина «авто-оставить» (entry-записи, вход notion_export)
  review_records.jsonl  — entry-записи корзины «на ручную проверку»
  dropped.csv           — отсеянное с причиной
  report.json           — счётчики и статистика дублей

Критерии — «критерии выборки РНФ» (territory × cartographic × period);
период по умолчанию: нижняя 1600, верхняя 1939 (конец 1930-х).
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "modules"))

from triggers import classify  # noqa: E402
from territories import UYEZD_QUERIES  # noqa: E402

# ── Территориальный охват (из справочника territories.py) ─────────────────────
GUB_STEMS = ("калуж", "перм", "смолен", "ярослав")

# Чужие губернии/регионы — явный признак «не наш» (авто-отсев, если нет нашего стема)
FOREIGN_STEMS = (
    "московск", "иркутск", "тверск", "орловск", "вологодск", "вятск", "костромск",
    "нижегородск", "тамбовск", "тульск", "рязанск", "владимирск", "новгородск",
    "псковск", "петербург", "петроград", "харьковск", "киевск", "казанск",
    "самарск", "саратовск", "воронежск", "курск", "пензенск", "оренбургск",
    "архангельск", "астраханск", "таврическ", "херсонск", "полтавск", "черниговск",
    "минск", "витебск", "могилёвск", "могилевск", "виленск", "гродненск",
    "лифляндск", "эстляндск", "курляндск", "ковенск", "варшавск", "сибир",
    "кавказ", "область войска", "уральск",
)


def _uyezd_stem(name: str) -> str:
    w = name.lower().replace("ё", "е")
    w = re.sub(r"\s+уезд.*$", "", w)
    w = re.sub(r"(ский|ской|цкий|нский|ный|ый|ий|ая|ое|ье)$", "", w)
    return w


UYEZD_STEMS = tuple(sorted({
    _uyezd_stem(u) for lst in UYEZD_QUERIES.values() for u in lst
}))
IN_SCOPE_STEMS = tuple(GUB_STEMS) + UYEZD_STEMS


def norm_text(*parts) -> str:
    return " ".join(p for p in parts if p).lower().replace("ё", "е")


def scope_tag(rec: dict) -> str:
    """in_scope | foreign | unclear — по нашим/чужим топонимам в названии+описании."""
    hay = norm_text(rec.get("title"), rec.get("description"), rec.get("place"))
    if any(s in hay for s in IN_SCOPE_STEMS):
        return "in_scope"
    if any(s in hay for s in FOREIGN_STEMS):
        return "foreign"
    return "unclear"


def norm_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip().lower()
    u = u.split("#")[0].split("?")[0]
    return u.rstrip("/")


def sec_key(source: str, rec: dict) -> str:
    """Вторичный ключ дедупа: нормализованное название + источник + нижний год."""
    title = re.sub(r"\s+", " ", (rec.get("title") or "").lower().replace("ё", "е")).strip()
    yf = rec.get("year_from")
    return f"{source}|{title}|{yf if yf is not None else ''}"


def period_ok(rec: dict, lo: int, hi: int) -> bool | None:
    """True в периоде, False вне, None если год не указан (решать вручную)."""
    yf, yt = rec.get("year_from"), rec.get("year_to")
    years = [y for y in (yf, yt) if isinstance(y, int)]
    if not years:
        return None
    # запись в периоде, если хотя бы одна из границ попадает в [lo, hi]
    if any(lo <= y <= hi for y in years):
        return True
    # диапазон целиком новее верхней планки или древнее нижней → вне
    return False


def load_existing(path: Path | None) -> tuple[set, set]:
    if not path:
        return set(), set()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    urls = {norm_url(u) for u in data.get("urls", []) if u}
    keys = set(data.get("keys", []))
    return urls, keys


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path, help="папка прогона с records_full.jsonl")
    ap.add_argument("--existing", type=Path, help="JSON уже-в-Notion: {urls:[], keys:[]}")
    ap.add_argument("--out", type=Path, help="папка вывода (default: <run>/review_run)")
    ap.add_argument("--lower-year", type=int, default=1600)
    ap.add_argument("--upper-year", type=int, default=1939)
    args = ap.parse_args()

    run_dir = args.run_dir
    src = run_dir / "records_full.jsonl"
    if not src.exists():
        print(f"Нет файла: {src}")
        sys.exit(1)
    out = args.out or (run_dir / "review_run")
    out.mkdir(parents=True, exist_ok=True)

    ex_urls, ex_keys = load_existing(args.existing)

    entries = [json.loads(ln) for ln in src.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]

    # ── Схлопывание дублей внутри прогона (URL → вторичный ключ) ──────────────
    groups: dict[str, dict] = {}
    order: list[str] = []
    dup_collapsed = 0
    for e in entries:
        rec = e.get("record", {})
        u = norm_url(rec.get("url", ""))
        key = u or sec_key(e.get("source", ""), rec)
        if key in groups:
            g = groups[key]
            g["hits"].append((e.get("territory", ""), e.get("keyword", "")))
            dup_collapsed += 1
        else:
            groups[key] = {"entry": e, "key": key, "url": u,
                           "hits": [(e.get("territory", ""), e.get("keyword", ""))]}
            order.append(key)

    accepted, review, dropped = [], [], []
    reasons = Counter()

    for key in order:
        g = groups[key]
        e = g["entry"]
        rec = e.get("record", {})
        u = g["url"]
        title = rec.get("title") or ""

        # 1) уже в Notion
        if (u and u in ex_urls) or (sec_key(e.get("source", ""), rec) in ex_keys):
            dropped.append((g, "already_in_notion"))
            reasons["already_in_notion"] += 1
            continue

        scope = scope_tag(rec)
        per = period_ok(rec, args.lower_year, args.upper_year)
        cls = classify(title)

        # 2) явно чужой регион и нет наших топонимов → отсев
        if scope == "foreign":
            dropped.append((g, "out_of_scope"))
            reasons["out_of_scope"] += 1
            continue
        # 3) явно вне периода (год указан и не попадает)
        if per is False:
            dropped.append((g, "out_of_period"))
            reasons["out_of_period"] += 1
            continue
        # 4) не картографический → отсев ТОЛЬКО если запись НЕ в нашем регионе.
        #    in_scope без маркера карты не выбрасываем: название часто не отражает
        #    содержание (карта губернии/уезда часто озаглавлена просто именем
        #    территории) — уводим на ручную проверку (ветка ниже).
        if cls == "negative" and scope != "in_scope":
            dropped.append((g, "not_cartographic"))
            reasons["not_cartographic"] += 1
            continue

        # 5) маршрутизация оставшихся
        if cls == "positive" and scope == "in_scope" and per in (True, None):
            g["bucket_reason"] = "auto_keep"
            accepted.append(g)
            reasons["auto_keep"] += 1
        else:
            # сомнительное / регион неясен / год неясен → ручная проверка
            tag = []
            if cls == "doubtful":
                tag.append("сомнительный тип")
            if cls == "negative":
                tag.append("нет маркера карты")
            if scope == "unclear":
                tag.append("регион неясен")
            if per is None:
                tag.append("год не указан")
            g["bucket_reason"] = ", ".join(tag) or "проверить"
            review.append(g)
            reasons["to_review"] += 1

    # ── Запись выходов ────────────────────────────────────────────────────────
    def _row(g):
        e = g["entry"]
        rec = e.get("record", {})
        terrs = "; ".join(sorted({t for t, _ in g["hits"] if t}))
        kws = "; ".join(sorted({k for _, k in g["hits"] if k}))
        return {
            "Источник": e.get("source", ""),
            "Территория": terrs,
            "Ключевое слово": kws,
            "Название": rec.get("title", ""),
            "Год от": rec.get("year_from", "") if rec.get("year_from") is not None else "",
            "Год до": rec.get("year_to", "") if rec.get("year_to") is not None else "",
            "URL": rec.get("url", ""),
            "Описание": rec.get("description", ""),
        }

    fields = ["Источник", "Территория", "Ключевое слово", "Название",
              "Год от", "Год до", "URL", "Описание", "Причина"]

    with (out / "review.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for g in review:
            row = _row(g)
            row["Причина"] = g.get("bucket_reason", "")
            w.writerow(row)

    with (out / "dropped.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for g, reason in dropped:
            row = _row(g)
            row["Причина"] = reason
            w.writerow(row)

    with (out / "accepted_records.jsonl").open("w", encoding="utf-8") as f:
        for g in accepted:
            f.write(json.dumps(g["entry"], ensure_ascii=False) + "\n")
    with (out / "review_records.jsonl").open("w", encoding="utf-8") as f:
        for g in review:
            f.write(json.dumps(g["entry"], ensure_ascii=False) + "\n")

    report = {
        "run_dir": str(run_dir),
        "input_records": len(entries),
        "unique_after_collapse": len(order),
        "duplicates_collapsed": dup_collapsed,
        "existing_urls_loaded": len(ex_urls),
        "buckets": {
            "auto_keep": len(accepted),
            "to_review": len(review),
            "dropped": len(dropped),
        },
        "drop_reasons": dict(reasons),
        "params": {"lower_year": args.lower_year, "upper_year": args.upper_year},
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

    print(f"Прогон: {run_dir.name}")
    print(f"  записей: {len(entries)}  → уникальных: {len(order)}  (схлопнуто дублей: {dup_collapsed})")
    print(f"  авто-оставить: {len(accepted)}  |  на ручную проверку: {len(review)}  |  отсеяно: {len(dropped)}")
    print(f"  причины отсева: {dict(reasons)}")
    print(f"  → {out}")


if __name__ == "__main__":
    main()
