"""Единый классификатор остановки постраничного сбора (все архивы/библиотеки).

Один детерминированный вердикт после каждого ответа страницы выдачи:
 more_pages       есть результаты и следующая страница -> продолжать
 reported_end     подтверждённый конец выдачи запроса -> следующий запрос
 ambiguous_empty  пусто без доказанного конца -> unverified, стоп без повтора
 real_barrier     401/403/429, CAPTCHA, redirect на login, фразы запрета -> стоп, эскалация человеку
 transport_error  сеть/таймаут/не-HTML -> политика ретраев транспорта

ПРИНЦИП: наличие формы логина / input[type=password] НЕ участвует в решении.
Кнопка «Войти» и скрытая форма в шапке -- постоянный элемент оформления многих
сайтов (ПрБ: header#header на каждой странице, вкл. пустые хвосты выдачи);
эвристика по ней дала ложный барьер authentication_or_login_form_unresolved на
prlib_catalog_full_20260917_v1 (страница «По вашему запросу нет результатов»,
HTTP 200). Решают только: HTTP-статус, redirect на login, CAPTCHA-виджеты,
сильные фразы запрета, число результатов, маркер конца, пагинатор.
Присутствие password-поля фиксируется информационным сигналом, не вердиктом.

Новый источник = новый SourceProfile (конфиг, не новый классификатор).
"""

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, parse_qsl
from bs4 import BeautifulSoup

MORE_PAGES = "more_pages"
REPORTED_END = "reported_end"
AMBIGUOUS_EMPTY = "ambiguous_empty"
REAL_BARRIER = "real_barrier"
TRANSPORT_ERROR = "transport_error"
LIMIT = 2 * 1024 * 1024
_BARRIER_STATUS = {
    401: "http_401_unauthorized",
    403: "http_403_forbidden",
    407: "http_407_proxy_auth",
    429: "http_429_rate_limited",
}
_LOGIN_PATH = re.compile(r"/(user/)?(login|signin|auth)(/|$|\?)", re.I)


@dataclass
class SourceProfile:
    """Сигналы конкретного источника; по умолчанию -- ПрБ (www.prlib.ru)."""

    name: str = "prlib"
    item_href: str = r"^/item/[0-9]+/?$"
    end_markers: tuple = (
        "по вашему запросу нет результатов",
        "по вашему запросу ничего не найдено",
        "ничего не найдено",
        "поиск не дал результатов",
    )
    barrier_phrases: tuple = (
        "verify you are human",
        "access denied",
        "доступ запрещен",
        "доступ запрещён",
        "authentication required",
        "login required",
        "требуется авторизация",
        "необходимо авторизоваться",
    )
    captcha_selectors: tuple = (
        ".g-recaptcha",
        ".h-captcha",
        "#captcha",
        "iframe[src*=captcha]",
    )
    page_param: str = "page"
    results_scope: str = "main"
    item_query_key: str = ""
    pager_href: str = ""
    empty_selector: str = ""
    # Explicit per-source policy for a secondary field with bounded,
    # documented incomplete pagination. It is not a global relaxation.
    accepted_partial_fields: tuple = ()
    accepted_partial_reasons: tuple = ()
    field_page_caps: tuple = ()
    pager_query_keys: tuple = ()


PRLIB = SourceProfile()
RGIA = SourceProfile(
    name="rgia",
    item_href=r"^/object/\d+$",
    end_markers=(
        "по вашему запросу ничего не найдено",
        "по вашему запросу нет результатов",
        "ничего не найдено",
    ),
    page_param="page",
    results_scope="body",
)


PERMKRAI = SourceProfile(
    name="permkrai",
    item_href=r"^/node/\d+$",
    end_markers=(
        "материалы не найдены",
        "ничего не найдено",
    ),
    page_param="page",
    results_scope="body",
)


RGADA = SourceProfile(
    name="rgada",
    item_href=r"^/poisk/index2\.php$",
    item_query_key="str",
    end_markers=(
        "просим вас проверить корректность поисковых данных или ввести запрос позже",
    ),
    page_param="page",
    results_scope="body",
    pager_href=r"^/poisk/index\.php$",
    empty_selector="form[name=frm]",
    accepted_partial_fields=("fund_name",),
    accepted_partial_reasons=("pager_classifier_mismatch", "repeated_page"),
    field_page_caps=(("fund_name", 6),),
    # Excludes the catalogue's unrelated fund-navigation links from a
    # list_name/fund_name result pager.
    pager_query_keys=("list_name", "fund_name", "Sk"),
)


def _page_number(url, param):
    for k, v in parse_qsl(urlsplit(url or "").query):
        if k == param and v.isdigit():
            return int(v)
    return 0


def _hidden(node):
    for ancestor in [node] + list(node.parents):
        if not getattr(ancestor, "attrs", None):
            continue
        style = re.sub(r"\s+", "", ancestor.get("style", "").lower())
        if (
            ancestor.has_attr("hidden")
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            return True
    return False


def _verdict(verdict, reason, signals, evidence):
    return {
        "verdict": verdict,
        "reason": reason,
        "signals": signals,
        "evidence": evidence,
    }


def classify_exception(exc):
    """Транспортное исключение (таймаут, обрыв, DNS) -> transport_error."""
    return _verdict(
        TRANSPORT_ERROR,
        "exception",
        ["exception:" + type(exc).__name__],
        {"error": str(exc)[:200]},
    )


def classify_response(
    status, content_type, body, url="", profile=PRLIB, redirect_location=""
):
    """Классифицировать ответ страницы выдачи. body -- bytes или str (HTML)."""
    signals = []
    evidence = {"url": url, "status": status}
    if status in _BARRIER_STATUS:
        return _verdict(
            REAL_BARRIER, _BARRIER_STATUS[status], ["http:" + str(status)], evidence
        )
    if status in (301, 302, 303, 307, 308):
        if redirect_location and _LOGIN_PATH.search(urlsplit(redirect_location).path):
            return _verdict(
                REAL_BARRIER,
                "redirect_to_login",
                ["location:" + redirect_location[:120]],
                evidence,
            )
        return _verdict(
            TRANSPORT_ERROR,
            "unexpected_redirect",
            ["location:" + (redirect_location or "")[:120]],
            evidence,
        )
    if status != 200:
        return _verdict(
            TRANSPORT_ERROR,
            "http_status_" + str(status),
            ["http:" + str(status)],
            evidence,
        )
    if isinstance(body, str):
        body = body.encode("utf-8", "replace")
    if len(body) > LIMIT:
        return _verdict(
            TRANSPORT_ERROR, "response_too_large", ["size:" + str(len(body))], evidence
        )
    if content_type and "html" not in content_type.lower():
        return _verdict(
            TRANSPORT_ERROR,
            "unexpected_content_type",
            ["content_type:" + content_type[:60]],
            evidence,
        )
    s = BeautifulSoup(body, "html.parser")
    for selector in profile.captcha_selectors:
        if s.select_one(selector):
            return _verdict(
                REAL_BARRIER, "captcha_widget", ["captcha:" + selector], evidence
            )
    if s.select_one("input[type=password]"):
        signals.append(
            "login_form_present_ignored"
        )  # информационно; в решении не участвует
    for node in s.select("script,style"):
        node.decompose()
    text = s.get_text(" ", strip=True).lower()
    for phrase in profile.barrier_phrases:
        if phrase in text:
            return _verdict(
                REAL_BARRIER, "barrier_phrase", signals + ["phrase:" + phrase], evidence
            )
    scope = s.select_one(profile.results_scope) or s
    pattern = re.compile(profile.item_href)

    def absolute_href(node):
        return urljoin(url, node.get("href", ""))

    items = [
        a
        for a in scope.select("a[href]")
        if pattern.match(urlsplit(absolute_href(a)).path)
        and (
            not profile.item_query_key
            or any(
                k == profile.item_query_key and v
                for k, v in parse_qsl(urlsplit(absolute_href(a)).query)
            )
        )
        and a.get_text(" ", strip=True)
        and not _hidden(a)
    ]
    current = _page_number(url, profile.page_param)
    pager_pattern = re.compile(profile.pager_href) if profile.pager_href else None
    has_next = False
    for a in s.select("a[href]"):
        href = absolute_href(a)
        rel = [r.lower() for r in (a.get("rel") or [])]
        is_profile_pager = not pager_pattern or bool(
            pager_pattern.match(urlsplit(href).path)
        )
        if is_profile_pager and profile.pager_query_keys:
            current_params = dict(parse_qsl(urlsplit(url).query))
            pager_params = dict(parse_qsl(urlsplit(href).query))
            for key in profile.pager_query_keys:
                if key in current_params and pager_params.get(key) != current_params[key]:
                    is_profile_pager = False
                    break
        if is_profile_pager and (
            "next" in rel or _page_number(href, profile.page_param) > current
        ):
            has_next = True
            break
    end_marker = next((m for m in profile.end_markers if m in text), None)
    evidence.update(
        items=len(items), page=current, has_next=has_next, end_marker=end_marker
    )
    if items:
        if has_next:
            return _verdict(MORE_PAGES, "results_with_next", signals, evidence)
        return _verdict(REPORTED_END, "last_page_no_next", signals, evidence)
    if end_marker:
        return _verdict(
            REPORTED_END,
            "empty_with_end_marker",
            signals + ["marker:" + end_marker],
            evidence,
        )
    if profile.empty_selector and s.select_one(profile.empty_selector):
        return _verdict(
            REPORTED_END,
            "empty_with_source_marker",
            signals + ["selector:" + profile.empty_selector],
            evidence,
        )
    return _verdict(AMBIGUOUS_EMPTY, "empty_without_end_marker", signals, evidence)
