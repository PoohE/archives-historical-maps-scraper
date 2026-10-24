"""Offline regression for v11 IPv4-only transport and frozen contract."""

import importlib.util
import socket
from pathlib import Path
from types import SimpleNamespace

import urllib3.util.connection as urllib3_util_connection


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260926_v11"


def test_v11_uses_ipv4_only_for_one_rgian_get_and_restores_urllib3():
    spec = importlib.util.spec_from_file_location("rgia_full_v11", PACKAGE / "run_catalog.py")
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    original_util = urllib3_util_connection.allowed_gai_family

    class Session:
        def get(self, url, **kwargs):
            assert url == "https://fgurgia.ru/robots.txt"
            assert urllib3_util_connection.allowed_gai_family() == socket.AF_INET
            return SimpleNamespace(
                status_code=200,
                headers={"Content-Type": "text/plain"},
                content=b"User-agent: *\nAllow: /\n",
                url=url,
            )

    result = runner.raw_http(Session(), "https://fgurgia.ru/robots.txt")
    assert result[0] == 200
    assert urllib3_util_connection.allowed_gai_family is original_util
    assert runner.manifest()["package"] == "rgia_catalog_full_handoff_20260926_v11"
