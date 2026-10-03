# -*- coding: utf-8 -*-
"""Зонд: как у ф.380 оп.21 (Пермская) листается дерево дел — `page` или `nPage`.

Зачем. Прогон v2 взял у каждой многостраничной описи ровно 20 дел (первую страницу) и
объявил «конец». Рабочий модуль `searcher_rgia._tree_params` шлёт номер страницы в `nPage`,
а `page` держит равным «1». Нужно живым запросом установить, какой параметр реально двигает
выдачу, — иначе пакет v3 починят не в ту сторону.

Проверяется на оп.21 (`object/2841185`, в state 37 страниц дерева): берём корень дел,
затем одну и ту же страницу запрашиваем двумя способами и сравниваем состав дел.
Паузы ≥4 с: fgurgia soft-банит под нагрузкой.
"""
import io
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OPIS = "2841185"
BASE = "https://fgurgia.ru"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
PAUSE = 4


def params(page: int, node_id="0", mode: str = "nPage") -> dict:
    """mode='nPage' — как в рабочем модуле; mode='page' — номер страницы в `page`."""
    p = {"page": "1", "nPage": str(page), "size": "", "id": str(node_id), "parentId": "",
         "objectType": "", "orderNumber": "0", "showPageList": "true", "count": "0",
         "alphabet": "", "tabId": "0", "completeWorkId": "-1"}
    if mode == "page":
        p["page"], p["nPage"] = str(page), "1"
    return p


def get_tree(s, ti, page, node_id="0", mode="nPage"):
    r = s.get(f"{BASE}/ajax/tree/{ti}", params=params(page, node_id, mode), timeout=40,
              headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/object/{OPIS}"})
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        return r.json(), ""
    except ValueError:
        return None, "не JSON: " + r.text[:120]


def describe(nodes):
    """Возвращает (id дел, строка pageList)."""
    ids, pager = [], ""
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        txt = re.sub(r"<[^>]+>", " ", str(n.get("text") or "")).strip()
        if n.get("id") in (None, "null") and re.fullmatch(r"[\d,]+", txt):
            pager = txt
        elif n.get("id"):
            ids.append(str(n["id"]))
    return ids, pager


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    r = s.get(f"{BASE}/object/{OPIS}", timeout=40)
    print(f"страница описи → {r.status_code}")
    m = re.search(r'data-search-index="(\d+)"', r.text)
    if not m:
        print("tree_index не найден")
        return
    ti = m.group(1)
    print("tree_index:", ti)

    time.sleep(PAUSE)
    root, err = get_tree(s, ti, 1)
    print("\nкорень:", err or f"узлов {len(root)}")
    if root is None:
        return
    # узел «Дела» — тот, у которого есть потомки
    cases_id = None
    for n in root:
        txt = re.sub(r"<[^>]+>", " ", str(n.get("text") or "")).strip()
        print(f"   id={n.get('id')} children={n.get('children')} {txt[:70]}")
        if n.get("id") and n.get("children"):
            cases_id = str(n["id"])
    node = cases_id or "0"
    print("узел для листания:", node)

    base_ids = None
    for mode in ("nPage", "page"):
        for page in (1, 2):
            time.sleep(PAUSE)
            nodes, err = get_tree(s, ti, page, node, mode)
            if nodes is None:
                print(f"\n{mode}={page}: {err}")
                continue
            ids, pager = describe(nodes)
            if mode == "nPage" and page == 1:
                base_ids = set(ids)
            new = "—" if base_ids is None else len(set(ids) - base_ids)
            print(f"\n{mode}={page}: дел {len(ids)}, pageList [{pager}], новых против 1-й стр.: {new}")
            print("   первые id:", ids[:4])


if __name__ == "__main__":
    main()
