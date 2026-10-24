"""Центральный фондовый каталог (ЦФК): поиск по ВСЕМ архивам России сразу.

Почему это важнее обхода архивов по одному. ЦФК — федеральная система Росархива, ищет по
составу Архивного фонда РФ до уровня ЕДИНИЦ ХРАНЕНИЯ. Проверка 20.10: «Карта Калужской
губернии (из библиотеки Д.Н. Василевского)» лежит в личном фонде Р-1707 в ЦГА Удмуртской
Республики — обход «архив за архивом» такого не найдёт в принципе. Спрашивать надо про
ПРЕДМЕТ у всего Архивного фонда.

⚠️ Грабли, на которых потеряно время 20.10:
 1. Сертификат российского УЦ не принят по умолчанию (`ERR_CERT_AUTHORITY_INVALID`) —
    подтверждает человек один раз в профиле `chrome-debug`.
 2. POST-запрос формы напрямую НЕ работает: сервер отвечает ошибкой ASP.NET «Ссылка на
    объект не указывает на экземпляр объекта» — форме нужны поля состояния.
 3. Это React-приложение: присваивание `input.value = …` оно ИГНОРИРУЕТ, поиск уходит с
    пустой строкой и честно возвращает нули. Значение ставится нативным сеттером
    `HTMLInputElement.prototype.value` + событие `input`, и только потом клик по «ПОИСК».
 4. Счётчика «Результаты с N по M из K» в DOM нет — число берётся из плиток «Найдено:»,
    их шесть: фонды, истор. справки, аннотации фондов, описи, аннотации описей,
    единицы хранения. Нас интересует шестая.

Запуск:
    python -B scripts_cfc/cfc_sweep.py --limit 3   # проба
    python -B scripts_cfc/cfc_sweep.py             # все запросы
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from cdp_fetch import Browser  # noqa: E402

OUT = ROOT / "output" / "cfc_sweep_20261020"
BASE = "https://cfc.rusarchives.ru/CFC-search/"

GUBERNII = ["Калужской", "Смоленской", "Ярославской", "Пермской"]
KINDS = ["карта", "план", "атлас", "чертеж", "межевой план", "геометрический план"]
UEZDY = {
    "Калужской": ["карта Боровского уезда", "карта Козельского уезда", "карта Медынского уезда",
                  "карта Мосальского уезда", "карта Тарусского уезда", "карта Жиздринского уезда"],
    "Смоленской": ["карта Вяземского уезда", "карта Гжатского уезда", "карта Дорогобужского уезда",
                   "карта Рославльского уезда", "карта Юхновского уезда", "карта Духовщинского уезда"],
    "Ярославской": ["карта Ростовского уезда", "карта Угличского уезда", "карта Мышкинского уезда",
                    "карта Пошехонского уезда", "карта Рыбинского уезда", "карта Мологского уезда"],
    "Пермской": ["карта Соликамского уезда", "карта Чердынского уезда", "карта Кунгурского уезда",
                 "карта Верхотурского уезда", "карта Шадринского уезда", "карта Оханского уезда"],
}

FOUND = re.compile(r"Найдено:\s*(\d+)")
# Карточка результата в тексте страницы
UNIT = re.compile(
    r"Единица хранения\s*№\s*([^\n.]*)\.?\s*(.*?)\n+Фонд\s*№\s*([^\n:]*):?\s*(.*?)\n+"
    r"Опись\s*№\s*([^\n:]*):?\s*(.*?)\n+(.*?)\n", re.S)


def queries() -> list[str]:
    out = []
    for g in GUBERNII:
        out.extend(f"{k} {g} губернии" for k in KINDS)
        out.extend(UEZDY[g])
    return out


class Cfc:
    def __init__(self) -> None:
        self.br = Browser(BASE)
        self.ws = self.br._conn()  # noqa: SLF001
        self._id = 100

    def ev(self, expr: str, wait: float = 0) -> str | None:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": "Runtime.evaluate",
                                 "params": {"expression": expr, "awaitPromise": True,
                                            "returnByValue": True}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                break
        if wait:
            time.sleep(wait)
        return msg.get("result", {}).get("result", {}).get("value")

    def search(self, q: str, wait: float = 11) -> str:
        js = """(() => {
          const i = document.querySelector('input[name=SearchString]');
          if (!i) return 'НЕТ ПОЛЯ';
          const setter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype, 'value').set;
          setter.call(i, %s);
          i.dispatchEvent(new Event('input', {bubbles: true}));
          const b = [...document.querySelectorAll('button,input[type=submit]')]
              .find(e => /ПОИСК/i.test(e.innerText || e.value || ''));
          if (!b) return 'НЕТ КНОПКИ';
          b.click();
          return 'ok';
        })()""" % json.dumps(q)
        self.ev(js, wait=wait)
        return self.ev("document.body.innerText") or ""

    def show_all_units(self, wait: float = 9) -> str:
        """Раскрыть раздел «Единицы хранения» — там кнопка ПОКАЗАТЬ ВСЕ."""
        js = """(() => {
          const blocks = [...document.querySelectorAll('div')]
              .filter(d => /Единицы хранения/.test(d.innerText || '') &&
                           /ПОКАЗАТЬ ВСЕ/.test(d.innerText || ''));
          const b = blocks.length
              ? [...blocks[blocks.length-1].querySelectorAll('button,a')]
                  .find(e => /ПОКАЗАТЬ ВСЕ/i.test(e.innerText || ''))
              : null;
          if (!b) return 'нет кнопки';
          b.click(); return 'ok';
        })()"""
        self.ev(js, wait=wait)
        return self.ev("document.body.innerText") or ""

    def close(self) -> None:
        self.br.close()


def parse_units(text: str, q: str) -> list[dict]:
    rows = []
    for m in UNIT.finditer(text):
        rows.append({
            "zapros": q,
            "n_delo": m.group(1).strip(),
            "zagolovok": re.sub(r"\s+", " ", m.group(2)).strip()[:400],
            "fond": m.group(3).strip(),
            "fond_nazvanie": re.sub(r"\s+", " ", m.group(4)).strip()[:160],
            "opis": m.group(5).strip(),
            "opis_nazvanie": re.sub(r"\s+", " ", m.group(6)).strip()[:120],
            "arhiv": re.sub(r"\s+", " ", m.group(7)).strip()[:140],
        })
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=2.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    qs = queries()
    if args.limit:
        qs = qs[: args.limit]
    print(f"запросов: {len(qs)}")

    cfc = Cfc()
    rows: list[dict] = []
    for i, q in enumerate(qs, 1):
        txt = cfc.search(q)
        found = FOUND.findall(txt)
        units = int(found[5]) if len(found) >= 6 else 0
        got = []
        if units:
            txt2 = cfc.show_all_units()
            got = parse_units(txt2, q)
            if not got:
                got = parse_units(txt, q)
        rows.extend(got)
        print(f"  {i:>3}/{len(qs)} {q[:46]:<46} ед.хр. {units:>4} | разобрано {len(got):>3}",
              flush=True)
        time.sleep(args.delay)
    cfc.close()

    if rows:
        seen, uniq = set(), []
        for r in rows:
            key = (r["arhiv"], r["fond"], r["opis"], r["n_delo"], r["zagolovok"][:60])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        with (OUT / "cfc_units.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(uniq[0]))
            w.writeheader()
            w.writerows(uniq)
        with (OUT / "cfc_units.jsonl").open("w", encoding="utf-8") as fh:
            for r in uniq:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\nкарточек всего: {len(rows)}, уникальных: {len(uniq)}")
        print(f"→ {OUT / 'cfc_units.csv'}")
    else:
        print("\nничего не разобрано")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
