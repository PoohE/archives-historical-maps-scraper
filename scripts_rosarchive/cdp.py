# -*- coding: utf-8 -*-
r"""Минимальный клиент Chrome DevTools Protocol: навигация и чтение страниц браузером пользователя.

Зачем: online.archives.ru и ряд региональных архивов геоблокируют нероссийские IP, а запросы
сессии идут через VPN-туннель (исходящий адрес Казахстана) — TCP не устанавливается вовсе.
Chrome у пользователя выведен из туннеля, поэтому ходим ЕГО браузером: подключение к
127.0.0.1:9222 локальное, страницы грузит Chrome.

Запуск отладочной копии (не трогая рабочие вкладки):
    chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\chrome-debug
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


def fetch(url: str, wait: float = 3.0, timeout: int = 60) -> tuple[str, str]:
    """Открывает URL во вкладке и возвращает (html, видимый текст)."""
    # Chrome отклоняет WebSocket с заголовком Origin (403 Rejected an incoming
    # WebSocket connection) — suppress_origin его не отправляет
    ws = create_connection(_tab(), timeout=timeout, suppress_origin=True)
    try:
        def send(method, params=None, _id=[0]):
            _id[0] += 1
            ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == _id[0]:
                    return msg

        send("Page.enable")
        send("Page.navigate", {"url": url})
        time.sleep(wait)
        html = send("Runtime.evaluate",
                    {"expression": "document.documentElement.outerHTML", "returnByValue": True})
        text = send("Runtime.evaluate",
                    {"expression": "document.body ? document.body.innerText : ''",
                     "returnByValue": True})
        return (html["result"]["result"].get("value") or "",
                text["result"]["result"].get("value") or "")
    finally:
        ws.close()
