"""Починка «Единицы хранения» у четырёх записей РГИА ф. 380 оп. 28.

Дефект найден 11.11.2026 при заливке: мост сообщил, что четыре «новых» дела оп. 28
уже в каталоге. Оказалось, у них «Единица хранения» записана одной литерой — «А», «Б»,
«В», «Г» — без номера дела 1005. Из-за этого сверка пакета по шифру считала их
отсутствующими, и они числились среди «62 новых записей РГИА», которых на деле нет.

Замер по всему каталогу (112 202 записи): записей с «Единицей хранения» из одной буквы
ровно эти четыре, больше нигде такого нет — дефект локальный.

Правка согласована пользователем 11.11.2026 («1 да»): это единственный случай, когда
правка меняет НЕПУСТОЕ поле, обычное правило проекта — заполнять только пустые.

  python fix_rgia380_op28_delo.py            # показать
  python fix_rgia380_op28_delo.py --apply    # применить
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402
from notion_upload_candidates import DB_ID, api  # noqa: E402

#: ссылка карточки РГИА → правильный номер дела
FIX = {
    "https://fgurgia.ru/object/2471039622": "1005 А",
    "https://fgurgia.ru/object/2471039642": "1005 Б",
    "https://fgurgia.ru/object/2471062636": "1005 В",
    "https://fgurgia.ru/object/2471039667": "1005 Г",
}
NOTE = ("Единица хранения исправлена 11.11.2026: в записи стояла одна литера «{was}» "
        "без номера дела — из-за этого сверка по шифру считала дело отсутствующим "
        "в каталоге.")


def plain(prop: dict) -> str:
    return "".join(x.get("plain_text", "") for x in prop.get("rich_text", [])).strip()


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    for url, correct in FIX.items():
        res = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query",
                  {"filter": {"property": "Ссылка на онлайн-архив",
                              "url": {"equals": url}}, "page_size": 2})
        hits = res.get("results", [])
        if len(hits) != 1:
            print(f"  ⚠️ {url}: найдено записей {len(hits)} — пропуск")
            continue
        page = hits[0]
        pr = page["properties"]
        was = plain(pr.get("Единица хранения", {}))
        note = plain(pr.get("Примечания", {}))
        if was == correct:
            print(f"  уже верно: {correct}")
            continue
        print(f"  {url}\n     «{was}» → «{correct}»")
        if not args.apply:
            continue
        add = NOTE.format(was=was)
        new_note = (note + " " + add).strip() if add not in note else note
        api("PATCH", f"https://api.notion.com/v1/pages/{page['id']}", {"properties": {
            "Единица хранения": {"rich_text": [
                {"type": "text", "text": {"content": correct}}]},
            "Примечания": {"rich_text": [
                {"type": "text", "text": {"content": new_note[:1900]}}]},
        }})
        print("     исправлено")

    if not args.apply:
        print("\nбез --apply ничего не изменено")


if __name__ == "__main__":
    main()
