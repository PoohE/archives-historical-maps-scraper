# -*- coding: utf-8 -*-
r"""Минимальный клиент Chrome DevTools Protocol: навигация и чтение страниц браузером пользователя.

Зачем: online.archives.ru и ряд региональных архивов геоблокируют нероссийские IP, а запросы
сессии идут через VPN-туннель (исходящий адрес Казахстана) — TCP не устанавливается вовсе.
Chrome у пользователя выведен из туннеля, поэтому ходим ЕГО браузером: подключение к
127.0.0.1:9222 локальное, страницы грузит Chrome.

Запуск отладочной копии (не трогая рабочие вкладки):
    chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\chrome-debug

Грабли:
  — уже запущенный Chrome игнорирует флаг отладки: новый процесс присоединяется к старому,
    порт не слушается. Нужна копия со своим --user-data-dir;
  — Chrome отклоняет WebSocket с заголовком Origin (403 «Rejected an incoming WebSocket
    connection») → suppress_origin=True;
  — у портала сертификат российского УЦ: исключение подтверждает пользователь вручную
    в браузере. Код TLS не ослабляет (DECISIONS.md: не возвращать verify=False в Росархиве).
"""
import json
import time
import urllib.request

try:
    from websocket import create_connection  # websocket-client
except ImportError as e:  # pragma: no cover
    raise SystemExit("нужен websocket-client: pip install websocket-client") from e

CDP = "http://127.0.0.1:9222"


def _tab() -> str:
    with urllib.request.urlopen(f"{CDP}/json/list", timeout=10) as r:
        tabs = [t for t in json.load(r) if t.get("type") == "page"]
    if not tabs:
        raise SystemExit("нет открытых вкладок в отладочном Chrome")
    return tabs[0]["webSocketDebuggerUrl"]


class Page:
    """Вкладка отладочного Chrome: навигация и выполнение выражений."""

    def __init__(self, timeout: int = 60):
        self.ws = create_connection(_tab(), timeout=timeout, suppress_origin=True)
        self._id = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                return msg

    def evaluate(self, expression: str):
        r = self.send("Runtime.evaluate",
                      {"expression": expression, "returnByValue": True, "awaitPromise": True})
        return r["result"]["result"].get("value")

    def goto(self, url: str, wait: float = 3.0) -> None:
        self.send("Page.enable")
        self.send("Page.navigate", {"url": url})
        time.sleep(wait)

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def fetch(url: str, wait: float = 3.0, timeout: int = 60) -> tuple[str, str]:
    """Открывает URL и возвращает (html, видимый текст)."""
    p = Page(timeout)
    try:
        p.goto(url, wait)
        return (p.evaluate("document.documentElement.outerHTML") or "",
                p.evaluate("document.body ? document.body.innerText : ''") or "")
    finally:
        p.close()


# Заголовки дел в списках описей УИАД обрезаны на сервере («… М-б...», класс is-truncated).
# Полный текст появляется после клика по «Полный/Краткий заголовок» (.list-item__collapse) —
# иначе теряются масштаб, размер листа и техника, то есть самое ценное для каталога.
EXPAND_JS = """(() => {
  document.querySelectorAll('.list-item__collapse').forEach(b => b.click());
  return document.querySelectorAll('.list-item__collapse').length;
})()"""

ITEMS_JS = """(() => {
  const out = [];
  document.querySelectorAll('.list-base__item--unit').forEach(li => {
    const a = li.querySelector('a[href*="/search/"]');
    const t = li.innerText.replace(/\\s+/g, ' ')
                          .replace(/Полный\\/Краткий заголовок/g, '').trim();
    if (a) out.push({href: a.getAttribute('href'), text: t});
  });
  return out;
})()"""


def fetch_units(url: str, wait: float = 4.0, expand_wait: float = 2.0,
                timeout: int = 60) -> tuple[list[dict], int]:
    """Список дел страницы описи с РАЗВЁРНУТЫМИ заголовками + объявленное «Всего»."""
    p = Page(timeout)
    try:
        p.goto(url, wait)
        p.evaluate(EXPAND_JS)
        time.sleep(expand_wait)
        items = p.evaluate(ITEMS_JS) or []
        total = p.evaluate(
            "(() => {const m=(document.body.innerText||'').match(/Всего[:\\s]*([\\d\\s]+)/);"
            "return m ? parseInt(m[1].replace(/\\s/g,''),10) : 0;})()") or 0
        return items, int(total)
    finally:
        p.close()
