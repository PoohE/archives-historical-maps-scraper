# -*- coding: utf-8 -*-
"""Самообучение отбору источников: уроки из решений человека (принято / отклонено).

Паттерн скопирован с `folder_lessons.py` (самообучение раскладке Articles, репо Ontology),
но модель данных другая: там снимок дерева папок, здесь — журнал решений приёмки.
Область действия — ТОЛЬКО проект «Поиск онлайн архив». В статьи и АИК не переносить.

Зачем. Пользователь принимает или отклоняет спорные записи; если это нигде не оседает,
следующий прогон совершает те же ошибки. Каждое решение — обучающий сигнал: из него
выводится либо частный урок (эта запись и почему), либо принцип (что отличает класс А от Б).

Команды:
    --show                     последние уроки и принципы (ЧИТАТЬ ПЕРЕД отбором)
    --diff                     решения, которых ещё нет в журнале (после новой проверки)
    --learn --note "…"         занести новые решения как уроки + обновить снимок
    --principle "…" [--from n,n,n]   записать выведенный принцип со ссылкой на случаи
    --supersede ID --note "…"  пометить прежний урок устаревшим (не перезаписывать молча)

Файлы:
    УРОКИ_ОТБОРА.jsonl   журнал (одна строка — один урок/принцип)
    УРОКИ_ОТБОРА.md      человекочитаемый рендер, его и читать перед работой
    .review_snapshot.json  какие решения уже разобраны (ключ — url)
"""
import argparse
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
JOURNAL = BASE / "УРОКИ_ОТБОРА.jsonl"
RENDER = BASE / "УРОКИ_ОТБОРА.md"
SNAPSHOT = BASE / "scripts_review" / ".review_snapshot.json"
DEFAULT_DECISIONS = BASE / "output" / "manual_review_20261004" / "decisions.csv"


def load_journal() -> list[dict]:
    if not JOURNAL.exists():
        return []
    return [json.loads(x) for x in JOURNAL.read_text(encoding="utf-8").splitlines() if x.strip()]


def append(entry: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_snapshot() -> set[str]:
    if not SNAPSHOT.exists():
        return set()
    return set(json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("seen_urls", []))


def save_snapshot(urls: set[str]) -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps({"seen_urls": sorted(urls), "updated": str(date.today())},
                                   ensure_ascii=False, indent=1), encoding="utf-8")


def read_decisions(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def render() -> None:
    items = load_journal()
    principles = [x for x in items if x.get("kind") == "principle" and not x.get("superseded")]
    cases = [x for x in items if x.get("kind") == "case" and not x.get("superseded")]
    old = [x for x in items if x.get("superseded")]

    lines = ["# Уроки отбора источников (самообучение на решениях человека)", "",
             "Механизм-собрат `folder_lessons` (раскладка Articles), но по решениям приёмки.",
             "**Область действия — только проект «Поиск онлайн архив».**", "",
             "**Порядок работы.** ПЕРЕД отбором или написанием гейта — прочитать этот файл.",
             "ПОСЛЕ очередной порции решений человека — `python scripts_review/catalog_review_lessons.py",
             "--learn --note \"…\"`; выведенное из нескольких случаев — `--principle`.",
             "Урок, противоречащий прежнему, не затирает его: прежний помечается `--supersede`,",
             "и расхождение выносится пользователю.", "",
             f"Обновлено: {date.today()} · принципов: {len(principles)} · частных уроков: {len(cases)}",
             "", "---", "", "## Принципы (выведены из нескольких случаев)", ""]
    if not principles:
        lines.append("_пока нет_")
    for p in principles:
        src = f" (случаи: {', '.join(map(str, p.get('from_cases', [])))})" if p.get("from_cases") else ""
        lines.append(f"- **{p['text']}**{src} — {p['date']}, id `{p['id']}`")

    lines += ["", "## Частные уроки (запись и почему)", ""]
    if not cases:
        lines.append("_пока нет_")
    for c in sorted(cases, key=lambda x: x.get("date", ""), reverse=True)[:80]:
        v = "ПРИНЯТО" if c.get("decision") == "yes" else "ОТКЛОНЕНО"
        lines.append(f"- [{v}] {c.get('title','')[:110]}")
        if c.get("note"):
            lines.append(f"  - {c['note']}")
        if c.get("url"):
            lines.append(f"  - {c['url']}")

    if old:
        lines += ["", "## Устаревшие (superseded)", ""]
        for o in old:
            lines.append(f"- ~~{o.get('text') or o.get('title','')[:100]}~~ — {o.get('superseded_note','')}")

    RENDER.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_show() -> None:
    if RENDER.exists():
        print(RENDER.read_text(encoding="utf-8"))
    else:
        print("журнала ещё нет — сначала --learn")


def cmd_diff(path: Path) -> None:
    seen = load_snapshot()
    rows = [r for r in read_decisions(path) if r.get("decision")]
    new = [r for r in rows if r.get("url") and r["url"] not in seen]
    print(f"решений в файле: {len(rows)}, уже разобрано: {len(rows) - len(new)}, новых: {len(new)}")
    for r in new[:20]:
        print(f"  [{r['decision']:3}] {r['title'][:90]}")
    if len(new) > 20:
        print(f"  … ещё {len(new) - 20}")


def cmd_learn(path: Path, note: str) -> None:
    seen = load_snapshot()
    rows = [r for r in read_decisions(path) if r.get("decision")]
    new = [r for r in rows if r.get("url") and r["url"] not in seen]
    today = str(date.today())
    for i, r in enumerate(new, 1):
        append({
            "id": f"case-{today}-{i:03d}", "kind": "case", "date": today,
            "decision": r["decision"], "source": r.get("source", ""),
            "territory": r.get("territory", ""), "title": r.get("title", ""),
            "url": r.get("url", ""), "question": r.get("question", ""),
            "note": note if i == 1 else "",
        })
        seen.add(r["url"])
    save_snapshot(seen)
    render()
    print(f"занесено уроков: {len(new)} | всего разобрано решений: {len(seen)}")
    print(f"рендер: {RENDER}")


def cmd_principle(text: str, from_cases: str) -> None:
    today = str(date.today())
    items = load_journal()
    n = sum(1 for x in items if x.get("kind") == "principle") + 1
    append({"id": f"principle-{n:02d}", "kind": "principle", "date": today, "text": text,
            "from_cases": [s.strip() for s in from_cases.split(",") if s.strip()] if from_cases else []})
    render()
    print(f"принцип записан: {text}")


def cmd_supersede(pid: str, note: str) -> None:
    items = load_journal()
    found = [x for x in items if x.get("id") == pid]
    if not found:
        print(f"урок {pid} не найден")
        return
    for x in items:
        if x.get("id") == pid:
            x["superseded"] = True
            x["superseded_note"] = note
            x["superseded_date"] = str(date.today())
    JOURNAL.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items) + "\n",
                       encoding="utf-8")
    render()
    print(f"урок {pid} помечен устаревшим. ⚠️ Расхождение с прежним правилом вынести пользователю.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--learn", action="store_true")
    ap.add_argument("--principle")
    ap.add_argument("--supersede")
    ap.add_argument("--note", default="")
    ap.add_argument("--from", dest="from_cases", default="")
    ap.add_argument("--decisions", default=str(DEFAULT_DECISIONS))
    a = ap.parse_args()
    path = Path(a.decisions)

    if a.principle:
        cmd_principle(a.principle, a.from_cases)
    elif a.supersede:
        cmd_supersede(a.supersede, a.note)
    elif a.learn:
        cmd_learn(path, a.note)
    elif a.diff:
        cmd_diff(path)
    else:
        cmd_show()


if __name__ == "__main__":
    main()
