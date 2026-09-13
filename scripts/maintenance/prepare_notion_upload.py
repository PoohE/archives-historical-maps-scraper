"""Подготовка 91 записи ГПИБ для загрузки в Notion."""
import csv, re, json
from pathlib import Path

CSV = Path("output/cloud/results_fixed.csv")
TARGET = re.compile(r"Калуж|Перм|Смолен|Ярослав", re.I)


def admin_level(title):
    t = title.lower()
    if any(w in t for w in ["губерни", "наместничеств", "провинци"]):
        return "Губерния"
    if any(w in t for w in ["уезда", "уезде", " уезд"]):
        return "Уезд"
    if "волост" in t:
        return "Волость"
    return None


def language(title):
    cyr = len(re.findall(r"[а-яёА-ЯЁ]", title))
    lat = len(re.findall(r"[a-zA-Z]", title))
    if lat > cyr:
        if re.search(r"\b(der|die|das|von|und)\b", title, re.I):
            return "Немецкий"
        if re.search(r"\b(de|du|la|le|les|et)\b", title, re.I):
            return "Французский"
        return "Латинский"
    return "Русский"


def modern_regions(title, territory):
    s = (title + " " + territory).lower()
    r = []
    if "калуж" in s:
        r.append("Калужская область")
    if "перм" in s:
        r.append("Пермский край")
    if "смолен" in s:
        r.append("Смоленская область")
    if "ярослав" in s:
        r.append("Ярославская область")
    return ", ".join(r)


def has_slippage(title):
    return bool(re.search(r"[а-яёА-ЯЁ]{14,}", title))


rows, seen = [], set()
with open(CSV, encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        url = row.get("URL", "")
        if url in seen or not TARGET.search(row.get("Название", "")):
            continue
        seen.add(url)
        rows.append(row)

pages = []
for row in rows:
    title = row["Название"].strip()
    yf = int(row["Год от"]) if row.get("Год от", "").strip() else None
    yt = int(row["Год до"]) if row.get("Год до", "").strip() else None
    url  = row.get("URL", "").strip()
    desc = row.get("Описание", "").strip()
    terr = row.get("Территория", "").strip()

    al   = admin_level(title)
    lang = language(title)
    mr   = modern_regions(title, terr)
    slip = has_slippage(title)

    props = {
        "Название источника": title,
        "Ссылка на онлайн-архив": url,
        "DC Type": "StillImage",
        "Автор внесения": "Агент",
        "date:Дата внесения:start": "2026-07-06",
        "date:Дата внесения:is_datetime": 0,
        "Геопривязка: статус": "Не выполнена",
        "Векторизация": "Нет",
        "OCR (распознавание текста)": "Нет",
        "Организация оцифровки": "ГПИБ России",
    }
    if yf:
        props["Год создания (нижняя)"] = yf
    if yt:
        props["Год создания (верхняя)"] = yt
    elif yf:
        props["Год создания (верхняя)"] = yf
    if desc:
        props["Описание"] = desc[:2000]
    if terr:
        props["Охватываемая территория"] = terr
    if al:
        props["Административный уровень"] = al
    if lang:
        props["Язык"] = lang
    if mr:
        props["Современные регионы"] = mr
    if slip:
        props["Сомнительных"] = "да"
        props["Примечания"] = "Возможное слипание слов — проверить вручную"

    pages.append(props)

with open("output/notion_upload.json", "w", encoding="utf-8") as f:
    json.dump(pages, f, ensure_ascii=False, indent=2)

print(f"Записей: {len(pages)}")
slip_count = sum(1 for p in pages if p.get("Сомнительных") == "да")
print(f"Со слипанием (на проверку): {slip_count}")
lang_cnt = {}
for p in pages:
    l = p.get("Язык", "?")
    lang_cnt[l] = lang_cnt.get(l, 0) + 1
print(f"Языки: {lang_cnt}")
al_cnt = {}
for p in pages:
    a = p.get("Административный уровень", "не определён")
    al_cnt[a] = al_cnt.get(a, 0) + 1
print(f"Адм. уровни: {al_cnt}")
