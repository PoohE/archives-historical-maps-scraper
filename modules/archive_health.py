"""
Мониторинг доступности онлайн-архивов: автоматическое обновление Notion.

Использование в run_search.py:
    from archive_health import ArchiveHealth
    health = ArchiveHealth()          # один раз в начале
    health.ok("rgo")                  # источник ответил нормально
    health.issue("rgo", "HTTP 403: доступ закрыт", "Попробовать через VPN")
    health.save()                     # в конце — записать всё в Notion
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── Маппинг library_id → Notion page ID (таблица «Архивы») ──────────────────
LIBRARY_PAGE_ID: dict[str, str] = {
    "rgo":          "3840ba89-eabe-81ba-97ac-cdb426a55076",  # Геопортал РГО
    "gpib":         "3920ba89-eabe-81d8-8da0-c14ad8609570",  # ГПИБ
    "prlib":        "3920ba89-eabe-811d-94c6-cee2dc3e4870",  # Президентская
    "runivers":     "3840ba89-eabe-8175-ac04-c6640a1720f3",  # Руниверс
    "nlr_cart":     "3920ba89-eabe-8198-bbd1-e4b067873904",  # РНБ
    "etomesto":     "3920ba89-eabe-81b6-a4a0-fd2e8465f5b2",  # ЭтоМесто
    "retromap":     "3920ba89-eabe-8139-8041-e6b1915ef405",  # Retromap
    "southklad":    "3920ba89-eabe-81eb-915e-d8114ebab237",  # Southklad
    "qmap":         "3920ba89-eabe-8105-a9ac-d7cf93d3a7ad",  # Q-map
    "permkrai":     "3920ba89-eabe-8124-9b00-fdc3af1ade46",  # Пермская краевая
    "kaluga_lib":   "3920ba89-eabe-81bb-88a5-d5375ce66bf1",  # Калужская
    "smolensk_lib": "3920ba89-eabe-818f-a217-f1ce2e2467cd",  # Смоленская
    "yaroslavl_lib":"3920ba89-eabe-81d6-964f-e03ffc3860bb",  # Ярославская
    # aonb — нет в Архивах, добавить вручную если нужно
}

# Известные способы обхода типичных проблем
_WORKAROUNDS: dict[str, str] = {
    "403": "Заблокирован по IP или требует авторизацию. Попробовать: VPN (Европа/Россия), изменить User-Agent, авторизоваться вручную и взять cookie.",
    "404": "Страница поиска изменила URL. Проверить актуальный адрес на сайте вручную.",
    "429": "Слишком частые запросы. Увеличить delay в _get() до 5–10 сек, добавить паузы между сессиями.",
    "503": "Сервер временно недоступен. Повторить через несколько часов или дней.",
    "timeout": "Сервер не отвечает в течение 25 сек. Попробовать в другое время суток. Возможно, сайт на техобслуживании.",
    "connection": "Нет сетевого соединения с сервером. Проверить блокировки, попробовать VPN.",
    "ssl": "Проблема с сертификатом SSL. Попробовать requests.get(..., verify=False) с осторожностью.",
    "empty": "Сайт отвечает, но поиск не возвращает результатов. Возможно, изменилась структура страницы — проверить CSS-селекторы вручную.",
}


def _guess_workaround(problem: str) -> str:
    """Предлагает обходной путь по ключевым словам проблемы."""
    pl = problem.lower()
    for key, workaround in _WORKAROUNDS.items():
        if key in pl:
            return workaround
    return "Проверить сайт вручную и обновить searcher_libraries.py если изменилась структура."


class ArchiveHealth:
    """
    Накапливает статусы источников за один запуск.
    В конце записывает все изменения в Notion одним пакетом.
    """

    def __init__(self) -> None:
        env = Path(__file__).parent.parent.parent / "Каталогизация" / ".env"
        with open(env, encoding="utf-8") as f:
            self._token = f.read().split("NOTION_TOKEN=")[1].split()[0]

        # {library_id: {"status": str, "problem": str, "workaround": str}}
        self._updates: dict[str, dict] = {}

    def ok(self, library_id: str) -> None:
        """Источник ответил нормально — пометить как Доступен."""
        # Обновляем только если раньше было не «Доступен»
        prev = self._updates.get(library_id, {}).get("status")
        if prev not in ("Доступен", None):
            return  # уже зафиксирована проблема — не перезатираем
        self._updates[library_id] = {
            "status": "Доступен",
            "web_search": "Полнотекстовый",
            "problem": "",
            "workaround": "",
        }

    def issue(self, library_id: str, problem: str,
              workaround: str | None = None) -> None:
        """
        Источник недоступен или вернул ошибку.
        workaround — если None, определяется автоматически.
        """
        if library_id not in LIBRARY_PAGE_ID:
            return  # нет записи в Notion — ничего не делаем
        wt = workaround if workaround is not None else _guess_workaround(problem)
        # Severity: если уже «Недоступен» — не понижать до «Частично»
        prev_status = self._updates.get(library_id, {}).get("status", "")
        if prev_status == "Недоступен":
            return
        self._updates[library_id] = {
            "status": "Недоступен",
            "web_search": "Недоступен",
            "problem": problem[:1800],   # лимит Notion rich_text
            "workaround": wt[:1800],
        }

    def partial(self, library_id: str, problem: str) -> None:
        """Источник частично работает (например, часть запросов проходит)."""
        if library_id not in LIBRARY_PAGE_ID:
            return
        if self._updates.get(library_id, {}).get("status") == "Недоступен":
            return
        self._updates[library_id] = {
            "status": "Частично",
            "problem": problem[:1800],
            "workaround": _guess_workaround(problem),
        }

    def save(self) -> None:
        """Записывает все накопленные статусы в Notion."""
        if not self._updates:
            return

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        print(f"\n[health] Обновляем статусы в Notion ({len(self._updates)} источников)...")
        ok = err = 0
        for lib_id, upd in self._updates.items():
            page_id = LIBRARY_PAGE_ID.get(lib_id)
            if not page_id:
                continue

            props: dict = {
                "Статус доступа": {"select": {"name": upd["status"]}},
            }
            if upd.get("web_search"):
                props["Веб-поиск"] = {"select": {"name": upd["web_search"]}}
            if upd.get("problem"):
                props["Проблема доступа"] = {
                    "rich_text": [{"text": {"content": upd["problem"]}}]
                }
            if upd.get("workaround"):
                props["Обходной путь"] = {
                    "rich_text": [{"text": {"content": upd["workaround"]}}]
                }

            req = urllib.request.Request(
                f"https://api.notion.com/v1/pages/{page_id}",
                data=json.dumps({"properties": props}).encode(),
                headers=headers, method="PATCH",
            )
            try:
                with urllib.request.urlopen(req) as r:
                    r.read()
                print(f"  ✓ {lib_id}: {upd['status']}")
                ok += 1
            except urllib.error.HTTPError as e:
                print(f"  ✗ {lib_id}: HTTP {e.code}")
                err += 1
            time.sleep(0.3)

        print(f"[health] Готово: {ok} обновлено, {err} ошибок")
