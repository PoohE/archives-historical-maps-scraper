"""Обогащение записей РГАДА из текста описи (URL-параметр opisanie).

Прогон РГАДА снял в title только хвост, а ПОЛНЫЙ текст описи лежит в URL (?opisanie=...).
Пример: «Планы дач Генерального и Специального межевания, 1746-1917 гг. (коллекция). Опись 613.
Часть 2. Губерния, уезд: Ярославская; Ярославский».

Из этого текста заполняем ПУСТЫЕ поля записи:
  Описание           ← весь текст описи (мастер-текст);
  Год нижняя/верхняя ← «NNNN-NNNN гг.» (охват коллекции);
  Серия / массив     ← «Генеральное межевание», если в тексте «межевани» (опись = РЕЕСТР
                       серийных карт Генмежевания, а не сами карты → привязка к серии);
  Тип источника+DC Type ← классификация по тексту (sweep_candidate_type).
«Номер в серии» не ставим (опись ≠ номер в серии; страж Д18).

Запуск: python scripts/maintenance/sweep_rgada_enrich.py [--apply]   (без флага — dry-run)
"""
import re
import sys
import time
import json
import urllib.request
from urllib.parse import urlsplit, parse_qs, unquote
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "maintenance"))
from sweep_candidate_type import TYPES, classify  # noqa: E402

ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
TOK = ""
for _ln in ENV.read_text(encoding="utf-8").splitlines():
    if _ln.strip().startswith("NOTION_TOKEN"):
        TOK = _ln.split("=", 1)[1].strip().strip('"').strip("'")
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}
DB = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
GENMEZH = "3830ba89-eabe-815f-ae01-c2ded60fa802"  # серия «Генеральное межевание»


def api(method, url, data=None):
    for att in range(4):
        try:
            rq = urllib.request.Request(
                url, data=json.dumps(data).encode() if data else None,
                headers=H, method=method)
            with urllib.request.urlopen(rq, timeout=40) as x:
                return json.load(x)
        except Exception:
            if att == 3:
                raise
            time.sleep(2)


def opisanie_of(url):
    q = parse_qs(urlsplit(url).query)
    return unquote(q.get("opisanie", [""])[0]).replace("<br>", " ").strip()


def rgada_records():
    out, cur = [], None
    while True:
        b = {"filter": {"property": "Ссылка на онлайн-архив", "url": {"contains": "rgada"}},
             "page_size": 100}
        if cur:
            b["start_cursor"] = cur
        r = api("POST", f"https://api.notion.com/v1/databases/{DB}/query", b)
        out += r["results"]
        if not r["has_more"]:
            break
        cur = r["next_cursor"]
    return out


def empty(pr, key):
    v = pr.get(key, {})
    t = v.get("type")
    return (not v.get(t)) if t else True


def main():
    apply = "--apply" in sys.argv
    print("РЕЖИМ:", "ПРИМЕНЕНИЕ" if apply else "DRY-RUN")
    recs = rgada_records()
    print(f"записей РГАДА: {len(recs)}")
    d_fill = y_fill = s_fill = t_fill = 0
    for pg in recs:
        pr = pg["properties"]
        url = (pr.get("Ссылка на онлайн-архив", {}) or {}).get("url") or ""
        op = opisanie_of(url)
        if not op:
            continue
        patch = {}
        if empty(pr, "Описание"):
            patch["Описание"] = {"rich_text": [{"text": {"content": op[:2000]}}]}
            d_fill += 1
        ym = re.search(r"(\d{4})\s*-\s*(\d{4})\s*гг", op)
        if ym:
            if empty(pr, "Год создания (нижняя)"):
                patch["Год создания (нижняя)"] = {"number": int(ym.group(1))}
                y_fill += 1
            if empty(pr, "Год создания (верхняя)"):
                patch["Год создания (верхняя)"] = {"number": int(ym.group(2))}
        if "межевани" in op.lower() and empty(pr, "Серия / массив"):
            patch["Серия / массив"] = {"relation": [{"id": GENMEZH}]}
            s_fill += 1
        code = classify(op)
        if code and code in TYPES and empty(pr, "Тип источника"):
            pid, dc = TYPES[code]
            patch["Тип источника"] = {"relation": [{"id": pid}]}
            if empty(pr, "DC Type"):
                patch["DC Type"] = {"select": {"name": dc}}
            t_fill += 1
        if patch and apply:
            api("PATCH", f"https://api.notion.com/v1/pages/{pg['id']}",
                {"properties": patch})
            time.sleep(0.34)
    print(f"\nОписание: {d_fill} | Год: {y_fill} | Серия(Генмежевание): {s_fill} | Тип: {t_fill}")


if __name__ == "__main__":
    main()
