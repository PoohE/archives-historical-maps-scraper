"""Доверие к российским корневым сертификатам — для архивных порталов Росархива.

Зачем. `online.archives.ru` (УИАД, электронные описи) и `guides.rusarchives.ru`
(путеводители по архивам) отдают сертификат, выданный **Russian Trusted Sub CA**
Минцифры. Этого корня нет ни в хранилище Python, ни в `certifi`, поэтому любой
запрос падает с `CERTIFICATE_VERIFY_FAILED` — и в октябре 2026 это читалось как
«портал лежит» или «блокировка», хотя хост отвечает нормально (разбор 16.11.2026).

Чего НЕ делаем: не отключаем проверку сертификата (`verify_mode = CERT_NONE`).
Отключение убирает и защиту от подмены; вместо этого добавляем в доверенные
три официальных сертификата Минцифры (корень и два промежуточных):

  scripts/certs/russian_trusted_root_ca.pem            — Root CA,     2022-03-01…2032-02-27
  scripts/certs/russian_trusted_sub_ca.pem             — Sub CA 2022, 2022-03-02…2027-03-06
  scripts/certs/russian_trusted_subca_ssl_rsa2024.pem  — Sub CA 2024, 2024-07-15…2029-07-19

⚠️ **Промежуточных Sub CA у Минцифры ДВА, и у них одинаковое CN.** Портал госуслуг
отдаёт выпуск 2022 года (серийный 0x1002), а `online.archives.ru` подписан выпуском
2024 года (`subca_ssl_rsa2024`) — с тем же `CN=Russian Trusted Sub CA`, но другим
ключом. Поэтому «добавил корни с gu-st.ru» не помогает: проверка всё равно падает
с `unable to get local issuer certificate`, и выглядит это как та же недоступность.
Нужный выпуск берётся по полю AIA самого сертификата сайта (`caIssuers`), сервер
промежуточный НЕ присылает — в цепочке приходит один лист.

Сроки: Sub CA 2022 истекает 06.03.2027, Sub CA 2024 — 19.07.2029. После истечения
или при смене выпуска перекачать: `python scripts/ru_tls.py --refresh`.

Бандл собирается как «certifi + российские сертификаты», то есть обычные сайты
продолжают проверяться штатно.

Применение в скриптах:

    from ru_tls import ru_urlopen
    with ru_urlopen(url, timeout=30) as r:
        body = r.read().decode("utf-8", "ignore")

или, если нужен контекст для своей библиотеки:

    from ru_tls import ru_ssl_context
    ctx = ru_ssl_context()

Самопроверка:  python scripts/ru_tls.py
Перекачать:    python scripts/ru_tls.py --refresh
"""
from __future__ import annotations

import argparse
import ssl
import sys
import urllib.request
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent / "certs"
ROOT_PEM = CERT_DIR / "russian_trusted_root_ca.pem"
SUB_PEM = CERT_DIR / "russian_trusted_sub_ca.pem"
BUNDLE = CERT_DIR / "ru_bundle.pem"

SUB2024_PEM = CERT_DIR / "russian_trusted_subca_ssl_rsa2024.pem"

SOURCES = {
    ROOT_PEM: "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt",
    SUB_PEM: "https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt",
    # Выпуск 2024 года — им подписан online.archives.ru; адрес взят из AIA его
    # сертификата. Зеркало: http://nuc-cdp.voskhod.ru/cdp/subca_ssl_rsa2024.crt
    SUB2024_PEM: "http://nuc-cdp.digital.gov.ru/cdp/subca_ssl_rsa2024.crt",
}

UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)"}

# Хосты, которым этот бандл нужен (для самопроверки и как список «кого он лечит»).
HOSTS = ("online.archives.ru", "guides.rusarchives.ru")


def download_certs() -> None:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    for path, url in SOURCES.items():
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            body = r.read()
        # CDP отдаёт DER, портал госуслуг — PEM; приводим к PEM в любом случае.
        if b"BEGIN CERTIFICATE" in body:
            path.write_bytes(body)
        else:
            try:
                from cryptography import x509
                from cryptography.hazmat.primitives.serialization import Encoding
            except ImportError:
                raise SystemExit(f"{url} отдал DER, а модуля cryptography нет") from None
            cert = x509.load_der_x509_certificate(body)
            path.write_bytes(cert.public_bytes(Encoding.PEM))
        print(f"скачан {path.name}: {len(body)} байт")
    BUNDLE.unlink(missing_ok=True)


def ru_bundle() -> Path:
    """Путь к бандлу «certifi + российские корни»; собирается при первом обращении."""
    if not all(p.exists() for p in SOURCES):
        download_certs()
    if not BUNDLE.exists():
        try:
            import certifi
            base = Path(certifi.where()).read_text(encoding="ascii", errors="ignore")
        except ImportError:        # certifi нет — берём то, что знает сам Python
            paths = ssl.get_default_verify_paths()
            base = ""
            if paths.cafile and Path(paths.cafile).exists():
                base = Path(paths.cafile).read_text(encoding="ascii", errors="ignore")
        parts = [base.rstrip()] + [
            p.read_text(encoding="ascii", errors="ignore").strip() for p in SOURCES
        ]
        BUNDLE.write_text("\n".join(p for p in parts if p) + "\n", encoding="ascii")
    return BUNDLE


def ru_ssl_context() -> ssl.SSLContext:
    """Контекст с ПОЛНОЙ проверкой сертификата, знающий корни Минцифры."""
    return ssl.create_default_context(cafile=str(ru_bundle()))


def ru_urlopen(url: str, timeout: int = 30, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or UA)
    return urllib.request.urlopen(req, timeout=timeout, context=ru_ssl_context())


def selftest() -> int:
    bad = 0
    print(f"бандл: {ru_bundle()}")
    for host in HOSTS:
        url = f"https://{host}/"
        try:
            with ru_urlopen(url, timeout=30) as r:
                n = len(r.read())
            print(f"  {host:<26} {r.status}  {n} байт — проверка сертификата пройдена")
        except Exception as e:                                  # noqa: BLE001
            bad += 1
            print(f"  {host:<26} ОШИБКА {type(e).__name__}: {str(e)[:80]}")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="перекачать корни и пересобрать бандл")
    args = ap.parse_args()
    if args.refresh:
        download_certs()
    sys.exit(selftest())


if __name__ == "__main__":
    main()
