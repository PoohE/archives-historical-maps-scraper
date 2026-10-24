"""Чтение страниц через браузер пользователя по CDP — общий модуль.

Зачем: часть порталов не отдаёт страницы обычным HTTP-запросом —
  * ГАЯО `af.yar-archives.ru` — WAF режет нероссийские адреса, квота на серверную сессию;
  * Пермская краевая `lib.permkrai.ru` — рвёт TLS-соединение (`SSL: UNEXPECTED_EOF`),
    работает только в живом браузере;
  * ГИС УИАД `online.archives.ru` — геоблок и сертификат российского УЦ.
Во всех трёх случаях рабочий путь один: открыть вкладку в Chrome пользователя и брать
страницы запросом ИЗНУТРИ неё — тем же origin и с теми же куками.

Дешевле открывать ОДНУ вкладку на сайт и внутри неё делать fetch: открытие вкладки на
каждую страницу вчетверо дороже самой страницы (замер 14.10 на ГАЯО: ~15 с против ~3 с),
браузер каждый раз заново тянет шрифты, метрику и recaptcha.

Требуется Chrome с отладочным портом: `chrome.exe --remote-debugging-port=9222
--user-data-dir=C:\\chrome-debug`. ⚠️ Chrome 155 не включает порт на обычном профиле —
нужен отдельный `--user-data-dir`, и Chrome перед запуском должен быть закрыт полностью.

Использование:
    from cdp_fetch import Browser
    br = Browser("https://lib.permkrai.ru/")
    html = br.get("https://lib.permkrai.ru/node/722")
    br.close()
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

CDP = "http://127.0.0.1:9222"
LOAD_WAIT = 6.0


def cdp(path: str, method: str = "GET"):
    req = urllib.request.Request(f"{CDP}{path}", method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def open_tab(url: str) -> dict:
    # адрес уходит в query самого CDP → кодировать ЦЕЛИКОМ, иначе обрыв на первом &
    return cdp("/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")


class Browser:
    """Одна вкладка на сайт; страницы берём внутри неё обычным fetch."""

    def __init__(self, home: str, load_wait: float = LOAD_WAIT) -> None:
        self.home = home
        self.tab = open_tab(home)
        time.sleep(load_wait)
        self.ws_url = self.tab["webSocketDebuggerUrl"]
        self._ws = None
        self.last_error: str | None = None

    def _conn(self):
        import websocket

        if self._ws is None:
            self._ws = websocket.create_connection(self.ws_url, timeout=60,
                                                   suppress_origin=True)
        return self._ws

    def get(self, url: str, tries: int = 3) -> str | None:
        """HTML страницы или None. Причина неудачи — в `last_error`."""
        expr = f"fetch({json.dumps(url)}, {{credentials:'include'}}).then(r => r.text())"
        self.last_error = None
        for attempt in range(1, tries + 1):
            try:
                ws = self._conn()
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "awaitPromise": True,
                                               "returnByValue": True}}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == 1:
                        break
                html = msg.get("result", {}).get("result", {}).get("value")
                if html:
                    return html
                self.last_error = "пустой ответ"
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:  # noqa: BLE001, S110
                    pass
                self._ws = None
                time.sleep(2 * attempt)
        return None

    def render(self, url: str, wait: float = 5.0, tries: int = 2) -> str | None:
        """DOM страницы ПОСЛЕ отрисовки скриптами.

        Нужен там, где список рисуется на клиенте и в исходном html его нет
        (Пермская краевая: рубрика `/node/722` приходит пустой оболочкой).
        Дороже `get`, поэтому применять только к таким страницам.
        """
        self.last_error = None
        for attempt in range(1, tries + 1):
            try:
                ws = self._conn()
                ws.send(json.dumps({"id": 10, "method": "Page.navigate",
                                    "params": {"url": url}}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == 10:
                        break
                time.sleep(wait)
                ws.send(json.dumps({"id": 11, "method": "Runtime.evaluate",
                                    "params": {"expression": "document.documentElement.outerHTML",
                                               "returnByValue": True}}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == 11:
                        break
                html = msg.get("result", {}).get("result", {}).get("value")
                if html:
                    return html
                self.last_error = "пустой DOM"
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:  # noqa: BLE001, S110
                    pass
                self._ws = None
                time.sleep(2 * attempt)
        return None

    def close(self) -> None:
        """Закрыть свою вкладку. ⚠️ Последнюю вкладку окна не закрываем: Chrome закроет
        окно целиком, и пользователь останется с пустым браузером (поймано 16.10)."""
        try:
            pages = [t for t in cdp("/json/list") if t.get("type") == "page"]
            if len(pages) > 1:
                cdp(f"/json/close/{self.tab['id']}")
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            if self._ws:
                self._ws.close()
        except Exception:  # noqa: BLE001, S110
            pass
