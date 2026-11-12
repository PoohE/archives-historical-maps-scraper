"""Единое хранилище найденного: SQLite-мастер + выгрузки CSV.

Зачем. Notion держит только то, что относится к четырём губерниям проекта. Всё остальное —
Азиатская Россия, Туркестан, Кавказ, Закаспийская область, чужие губернии — нужно для
пособия и статей, но в каталог не идёт. Раньше это жило в разрозненных файлах прогонов
и в scope_drops, то есть фактически было недоступно без нового поиска.

Мастер — SQLite, потому что к нему можно обратиться выборочно: ответ на запрос приходит
строками, а не файлом целиком. CSV генерируется из него для Excel и для человека.

Таблицы:
  istochniki — всё найденное, по одной строке на карточку (ключ «держатель:идентификатор»)
  resheniya  — журнал решений по охвату: что и почему признано вне скоупа

  python store_build.py init      # создать базу и влить всё, что уже есть
  python store_build.py export    # выгрузить CSV
  python store_build.py stats     # что в базе
"""

import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные"
)
DB = DATA / "найденные_источники.sqlite"
WORKDIR = ROOT / "output" / "work_2026-11-08"
PKG = ROOT / "output" / "series_package_20261107"

GUB = {"Калужск": "Калужская", "Смоленск": "Смоленская",
       "Ярославск": "Ярославская", "Пермск": "Пермская"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS istochniki (
  klyuch        TEXT PRIMARY KEY,   -- держатель:идентификатор карточки
  derzhatel     TEXT,
  url           TEXT,
  nazvanie      TEXT,               -- как нашли
  nazvanie_polnoe TEXT,             -- ISBD с карточки
  seriya        TEXT,
  gubernii      TEXT,               -- выявленные из названия губернии проекта
  v_skoupe      INTEGER,            -- 1 — относится к четырём губерниям
  masshtab      INTEGER,
  masshtab_text TEXT,
  shifr         TEXT,
  god_ot        INTEGER,
  god_do        INTEGER,
  listy         TEXT,
  razmer        TEXT,
  istochnik     TEXT,               -- откуда узнали: прогон, пакет, scope_drops…
  status        TEXT,
  notion_id     TEXT,               -- заполняется при внесении в каталог
  primechanie   TEXT,
  ts            TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS i_ser  ON istochniki(seriya);
CREATE INDEX IF NOT EXISTS i_skp  ON istochniki(v_skoupe);
CREATE INDEX IF NOT EXISTS i_der  ON istochniki(derzhatel);
CREATE INDEX IF NOT EXISTS i_not  ON istochniki(notion_id);

CREATE TABLE IF NOT EXISTS resheniya (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  klyuch    TEXT,
  reshenie  TEXT,     -- «вне охвата», «вернуть», «кандидат»
  prichina  TEXT,
  kto       TEXT,
  ts        TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS i_res ON resheniya(klyuch);
"""


def gub_from(text: str) -> str:
    return "; ".join(dict.fromkeys(v for k, v in GUB.items() if k in (text or "")))


def upsert(con: sqlite3.Connection, row: dict) -> None:
    """Доливает, не затирая уже заполненное непустым."""
    cols = [c for c in row if c != "klyuch"]
    sets = ", ".join(f"{c}=COALESCE(NULLIF(excluded.{c},''), {c})" for c in cols)
    con.execute(
        f"INSERT INTO istochniki (klyuch,{','.join(cols)}) "
        f"VALUES (?{',?' * len(cols)}) "
        f"ON CONFLICT(klyuch) DO UPDATE SET {sets}",
        [row["klyuch"]] + [row[c] for c in cols],
    )


def ingest_jsonl(con: sqlite3.Connection, path: Path, src: str) -> int:
    if not path.exists():
        return 0
    n = 0
    for ln in path.open(encoding="utf-8"):
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        key = r.get("key") or r.get("klyuch")
        if not key:
            continue
        title = r.get("zagolovok_polnyi") or r.get("zagolovok") or ""
        gub = r.get("gub_serii") or gub_from(title)
        upsert(con, {
            "klyuch": key,
            "derzhatel": key.split(":", 1)[0],
            "url": r.get("url") or r.get("record_url") or "",
            "nazvanie": r.get("zagolovok") or "",
            "nazvanie_polnoe": r.get("zagolovok_polnyi") or "",
            "seriya": r.get("seriya") or r.get("серия") or "",
            "gubernii": gub,
            "v_skoupe": 1 if gub else 0,
            "masshtab": r.get("scale") or None,
            "masshtab_text": r.get("scale_ctx") or "",
            "shifr": r.get("shelf") or "",
            "god_ot": r.get("data_nachato") or None,
            "god_do": r.get("data_okoncheno") or None,
            "istochnik": r.get("istochnik") or src,
            "status": r.get("status") or "",
            "primechanie": (r.get("primechanie") or "")[:600],
        })
        n += 1
    con.commit()
    return n


def ingest_drops(con: sqlite3.Connection) -> int:
    """Отсев прежних прогонов: он не мусор, а материал для пересмотра охвата.

    Строка отсева устроена так: сверху source / territory / keyword / scope_drop_reason,
    а сама карточка — во вложенном record. Причина отсева НЕ всегда региональная:
    встречается not_cartographic при territory «Калужская губерния», то есть запись
    по нашей губернии, снятая предметным гейтом.
    """
    n = 0
    for p in sorted((ROOT / "output").glob("*/scope_drops.jsonl")):
        src = f"scope_drops/{p.parent.name}"
        batch = 0
        for ln in p.open(encoding="utf-8"):
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            rec = r.get("record") or {}
            url = rec.get("url") or r.get("url") or ""
            ident = rec.get("identifier") or re.sub(r"\W+", "", url)[-24:]
            if not ident:
                continue
            title = rec.get("title") or ""
            terr = r.get("territory") or ""
            gub = gub_from(f"{terr} {title}")
            prichina = r.get("scope_drop_reason") or ""
            upsert(con, {
                "klyuch": f"ОТСЕВ:{ident}",
                "derzhatel": rec.get("source_lib") or r.get("source") or "",
                "url": url,
                "nazvanie": str(title)[:500],
                "seriya": "",
                "gubernii": gub,
                # отсев в Notion не идёт, но пометку о губернии сохраняем
                "v_skoupe": 0,
                "god_ot": None,
                "istochnik": src,
                "status": f"отсеян гейтом: {prichina}" if prichina else "отсеян гейтом",
                "primechanie": (f"территория прогона: {terr}; ключевое слово: "
                                f"{r.get('keyword') or ''}; автор: {rec.get('author') or ''}; "
                                f"место: {rec.get('place') or ''}")[:600],
            })
            n += 1
            batch += 1
            if batch % 5000 == 0:
                con.commit()
        con.commit()
        print(f"    {batch:>6}  {p.parent.name}")
    return n


def init() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    tot = 0
    for path, src in (
        (WORKDIR / "harvested.jsonl", "добор 08.11"),
        (WORKDIR / "work.jsonl", "прогон 08.11"),
        (PKG / "package_enriched.jsonl", "пакет 07.11"),
        (PKG / "package_ready.jsonl", "пакет 07.11"),
        (PKG / "package_still_human.jsonl", "пакет 07.11, нужен человек"),
        (PKG / "package_held_seriya11.jsonl", "пакет 07.11, отложено (серия 11)"),
    ):
        k = ingest_jsonl(con, path, src)
        print(f"  {k:>6}  {path.name}")
        tot += k
    k = ingest_drops(con)
    print(f"  {k:>6}  scope_drops (отсев прежних прогонов)")
    tot += k
    print(f"\nвсего обработано строк: {tot}")
    stats(con)
    con.close()


def stats(con: sqlite3.Connection | None = None) -> None:
    own = con is None
    con = con or sqlite3.connect(DB)
    q = con.execute
    print(f"\nбаза: {DB}")
    print(f"  всего карточек:        {q('SELECT COUNT(*) FROM istochniki').fetchone()[0]}")
    print(f"  в скоупе (4 губернии): {q('SELECT COUNT(*) FROM istochniki WHERE v_skoupe=1').fetchone()[0]}")
    print(f"  вне скоупа:            {q('SELECT COUNT(*) FROM istochniki WHERE v_skoupe=0').fetchone()[0]}")
    n_title = q("SELECT COUNT(*) FROM istochniki WHERE nazvanie_polnoe <> ''").fetchone()[0]
    n_shifr = q("SELECT COUNT(*) FROM istochniki WHERE shifr <> ''").fetchone()[0]
    n_notion = q("SELECT COUNT(*) FROM istochniki "
                 "WHERE notion_id IS NOT NULL AND notion_id <> ''").fetchone()[0]
    print(f"  с полным названием:    {n_title}")
    print(f"  с шифром хранения:     {n_shifr}")
    print(f"  уже в Notion:          {n_notion}")
    print("\n  по сериям (топ-12):")
    for s, n in q("SELECT seriya, COUNT(*) c FROM istochniki WHERE seriya<>'' "
                  "GROUP BY seriya ORDER BY c DESC LIMIT 12"):
        print(f"    {n:>6}  {s[:66]}")
    if own:
        con.close()


def export() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    jobs = [
        ("НАЙДЕННОЕ_полное.csv", "SELECT * FROM istochniki ORDER BY seriya, derzhatel, nazvanie"),
        ("НАЙДЕННОЕ_вне_скоупа.csv",
         "SELECT * FROM istochniki WHERE v_skoupe=0 ORDER BY seriya, derzhatel"),
        ("НАЙДЕННОЕ_для_notion.csv",
         "SELECT * FROM istochniki WHERE v_skoupe=1 AND (notion_id IS NULL OR notion_id='') "
         "ORDER BY seriya, derzhatel"),
    ]
    for name, sql in jobs:
        rows = con.execute(sql).fetchall()
        p = DATA / name
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=";")
                w.writeheader()
                for r in rows:
                    w.writerow(dict(r))
        print(f"  {len(rows):>6}  {p}")
    con.close()


if __name__ == "__main__":
    fix_stdout()
    mode = sys.argv[1] if len(sys.argv) > 1 else "stats"
    {"init": init, "export": export, "stats": stats}[mode]()
