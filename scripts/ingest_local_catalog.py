"""Ингест/ретрофит локальных каталогов коллег (ветка-1) в «Каталог» Notion.

Вход: структурированные CSV коллег (папка `sourse/`: колонки Губерния/Уезд/Архив/Фонд/Опись/
Дело/Название/Год/Листов/Примечание/Ссылка[/Описание/Что заказывать]). Маппит их на поля v1.6 и
заливает в каталог: если запись уже есть (по URL или по шифру) — ДОЗАПОЛНЯЕТ пустые поля
(retrofit, защищённые поля не трогает), если нет — создаёт кандидата.

Переиспользует общие модули: territory_resolve (территория/регион), sweep_candidate_type
(типизация A1–C8 + DC Type), notion_upload_candidates.archives_map (relation «Архив хранения»).

CLI:
  python scripts/ingest_local_catalog.py [csv...] [--archives РГВИА,ГАРФ] [--apply] [--date 2026-09-27]
Без csv — берёт sourse/kaluga.csv + sourse/perm.csv. Без --apply — dry-run.
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "modules"))
sys.path.insert(0, str(HERE / "maintenance"))
import territory_resolve as tr  # noqa: E402
from sweep_candidate_type import TYPES, classify  # noqa: E402
from notion_upload_candidates import archives_map, HOLDER_ALIASES  # noqa: E402

DB = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
TERR_DB = "3920ba89-eabe-81a2-86a2-d50d1bfee1c0"
REG_DB = "6c6a3cfb-8d87-491e-8ce6-da7194bc857b"
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
SOURSE = HERE.parent / "sourse"
TOK = ""
for _ln in ENV.read_text(encoding="utf-8").splitlines():
    if _ln.strip().startswith("NOTION_TOKEN"):
        TOK = _ln.split("=", 1)[1].strip().strip('"').strip("'")
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}

# защищённые при ретрофите (не перезаписывать)
PROTECTED = {"Автор внесения", "Дата внесения", "Статус приёмки",
             "Геопривязка: статус", "Векторизация", "OCR (распознавание текста)"}

# псевдонимы колонок → канонический ключ
COLMAP = {
    "губерния": "gub", "уезд": "uezd", "архив": "arch", "фонд": "fund",
    "опись": "opis", "дело": "delo", "название": "title", "год": "year",
    "листов": "sheets", "примечание": "note", "ссылка": "url",
    "описание": "descr", "что заказывать": "order",
}


def api(method, url, data=None):
    for att in range(4):
        try:
            rq = urllib.request.Request(
                url, data=json.dumps(data).encode() if data else None,
                headers=H, method=method)
            with urllib.request.urlopen(rq, timeout=40) as x:
                return json.load(x)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e
        except Exception:
            if att == 3:
                raise
            time.sleep(2)


def read_csv(path):
    txt = path.read_bytes().decode("utf-8-sig", errors="replace")
    rows = []
    for raw in csv.DictReader(io.StringIO(txt)):
        r = {}
        for k, v in raw.items():
            key = COLMAP.get((k or "").strip().lower())
            if key:
                r[key] = (v or "").strip()
        rows.append(r)
    return rows


def parse_year(s):
    s = (s or "").strip().lower().replace("ё", "е")
    if not s or s in ("б/д", "б.д.", "бд", "н/д", "-", "?", "—", "нд"):
        return (None, None)
    s = s.replace("около", "").replace("ок.", "").strip()
    century = bool(re.search(r"\bвв?\b|\bвек", s)) or bool(re.search(r"\d\s*в\b", s))
    if century:
        m = re.search(r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*вв?", s)  # 18-19 вв
        if m:
            return ((int(m.group(1)) - 1) * 100 + 1, int(m.group(2)) * 100)
        m = re.search(r"(\d{2})\s*-?е\s*(\d{1,2})\s*в", s)  # 80е 18 в
        if m:
            base = (int(m.group(2)) - 1) * 100
            return (base + int(m.group(1)), base + int(m.group(1)) + 9)
        m = re.search(r"(\d{1,2})\s*в", s)  # 18 в
        if m:
            c = int(m.group(1))
            return ((c - 1) * 100 + 1, c * 100)
        return (None, None)
    m = re.search(r"(1[5-9]\d\d)\s*[-–—]\s*(1[5-9]\d\d)", s)  # 1847-1848
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r"\b(1[5-9]\d\d)\b", s)  # 1829
    if m:
        return (int(m.group(1)), int(m.group(1)))
    return (None, None)


def norm_url(u):
    u = (u or "").strip()
    u = re.sub(r"#.*$", "", u).rstrip("/")
    return u


def shifr(r):
    parts = []
    if r.get("arch"):
        parts.append(r["arch"])
    if r.get("fund"):
        parts.append(f"Ф.{r['fund']}")
    if r.get("opis"):
        parts.append(f"Оп.{r['opis']}")
    if r.get("delo"):
        parts.append(f"Д.{r['delo']}")
    return ".".join(parts)


def find_page(url, shf):
    """Существующая запись по URL (по хвосту id) или по «Библиотечный шифр»."""
    if url:
        tail = norm_url(url).split("/")[-1]
        if tail:
            r = api("POST", f"https://api.notion.com/v1/databases/{DB}/query",
                    {"filter": {"property": "Ссылка на онлайн-архив",
                                "url": {"contains": tail}}, "page_size": 1})
            if r["results"]:
                return r["results"][0]
    if shf:
        r = api("POST", f"https://api.notion.com/v1/databases/{DB}/query",
                {"filter": {"property": "Библиотечный шифр",
                            "rich_text": {"equals": shf}}, "page_size": 1})
        if r["results"]:
            return r["results"][0]
    return None


def compose_descr(r):
    # «Листов» НЕ сюда — это локатор листов дела, поле «Листы / страницы» (канон поле 7).
    bits = []
    if r.get("descr"):
        bits.append(r["descr"])
    if r.get("note"):
        bits.append(r["note"])
    return " — ".join(bits)


def sheets_locator(r):
    """CSV «Листов» → значение поля «Листы / страницы» (листы дела в месте хранения)."""
    s = (r.get("sheets") or "").strip()
    if not s:
        return ""
    return s if any(c.isalpha() for c in s) else f"{s} л."


def build_props(r, terr_idx, terr_gub, reg_idx, arch_map):
    title = r.get("title") or ""
    if not title and r.get("descr"):
        title = r["descr"][:90].rstrip() + ("…" if len(r["descr"]) > 90 else "")
    url = norm_url(r.get("url"))
    props = {}
    if title:
        props["Название источника"] = {"title": [{"text": {"content": title[:2000]}}]}
    if url:
        props["Ссылка на онлайн-архив"] = {"url": url}
    # Архив хранения (relation)
    arch = (r.get("arch") or "").lower()
    if arch:
        aid = arch_map.get(HOLDER_ALIASES.get(arch, arch)) or arch_map.get(arch)
        if aid:
            props["Архив хранения"] = {"relation": [{"id": aid}]}
    # Архивный шифр РАЗЛОЖЕН по полям Фонд/Опись/Единица (дело). Композит «РГВИА. Ф. N…» собирает
    # формула поля «Шифр архива» — сюда НЕ пишем. «Библиотечный шифр» — только библиотеки/порталы,
    # у архивных дел (эти CSV коллег — РГВИА/РГИА/ГАРФ/РГАДА) НЕ заполняем.
    for key, col in (("fund", "Фонд"), ("opis", "Опись"), ("delo", "Единица хранения")):
        if r.get(key):
            props[col] = {"rich_text": [{"text": {"content": r[key]}}]}
    loc = sheets_locator(r)  # листы дела → «Листы / страницы» (канон поле 7)
    if loc:
        props["Листы / страницы"] = {"rich_text": [{"text": {"content": loc}}]}
    # годы
    lo, hi = parse_year(r.get("year"))
    if lo is not None:
        props["Год создания (нижняя)"] = {"number": lo}
    if hi is not None:
        props["Год создания (верхняя)"] = {"number": hi}
    # описание
    descr = compose_descr(r)
    if descr:
        props["Описание"] = {"rich_text": [{"text": {"content": descr[:2000]}}]}
    if r.get("order"):
        props["Примечания"] = {"rich_text": [{"text": {"content": "Что заказывать: " + r["order"][:1900]}}]}
    # территория/регион (из Губернии+Уезда как явные hints — надёжнее парсинга названия)
    hints = []
    if r.get("uezd"):
        hints.append(r["uezd"])              # уезд-прилагательное → запись-уезд
    if r.get("gub"):
        hints.append(f"{r['gub']} губерния")  # губ-уровень → запись-губерния
    terr_ids, reg_ids = tr.resolve(title, url, terr_idx, terr_gub, reg_idx, hints=hints)
    if terr_ids:
        props["Охватываемая территория"] = {"relation": [{"id": i} for i in terr_ids]}
    if reg_ids:
        props["Современные регионы"] = {"relation": [{"id": i} for i in reg_ids]}
    # тип источника + DC Type
    code = classify(title)
    if code and code in TYPES:
        pid, dc = TYPES[code]
        props["Тип источника"] = {"relation": [{"id": pid}]}
        props["DC Type"] = {"select": {"name": dc}}
    return props, title


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="*", type=Path)
    ap.add_argument("--archives", default="", help="фильтр по архивам через запятую (РГВИА,ГАРФ)")
    ap.add_argument("--date", default="2026-09-27")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    files = a.csv or [SOURSE / "kaluga.csv", SOURSE / "perm.csv"]
    arch_filter = {x.strip().upper() for x in a.archives.split(",") if x.strip()}
    print("РЕЖИМ:", "ПРИМЕНЕНИЕ" if a.apply else "DRY-RUN")
    if arch_filter:
        print("фильтр архивов:", ", ".join(sorted(arch_filter)))

    terr_idx, terr_gub, reg_idx = tr.load_indexes(api, TERR_DB, REG_DB)
    arch_map = archives_map()
    print(f"справочники: территорий {len(terr_idx)}, регионов {len(reg_idx)}, архивов {len(arch_map)}")

    rows = []
    for f in files:
        rr = read_csv(f)
        rows += rr
        print(f"  {f.name}: {len(rr)} строк")

    created = updated = skipped = 0
    for r in rows:
        if arch_filter and (r.get("arch") or "").upper() not in arch_filter:
            continue
        props, title = build_props(r, terr_idx, terr_gub, reg_idx, arch_map)
        if "Название источника" not in props:
            skipped += 1
            continue
        existing = find_page(norm_url(r.get("url")), shifr(r))
        if existing is None:
            props["Статус приёмки"] = {"select": {"name": "кандидат"}}
            props["Автор внесения"] = {"select": {"name": "Агент"}}
            props["Дата внесения"] = {"date": {"start": a.date}}
            created += 1
            if a.apply:
                api("POST", "https://api.notion.com/v1/pages",
                    {"parent": {"database_id": DB}, "properties": props})
                time.sleep(0.34)
        else:
            pr = existing["properties"]
            upd = {}
            for k, v in props.items():
                if k in PROTECTED:
                    continue
                cur = pr.get(k, {})
                t = cur.get("type")
                empty = (not cur.get(t)) if t else True
                if empty:
                    upd[k] = v
            if upd:
                updated += 1
                if a.apply:
                    api("PATCH", f"https://api.notion.com/v1/pages/{existing['id']}",
                        {"properties": upd})
                    time.sleep(0.34)
            else:
                skipped += 1

    print(f"\nсоздано: {created} | дозаполнено: {updated} | без изменений/пропущено: {skipped}")


if __name__ == "__main__":
    main()
