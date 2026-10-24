"""Offline contract test for frozen five-GET RGIA jstree probe."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_jstree_probe_handoff_20260922_v2"
FIXTURES = ROOT / "output/rgia_fixtures_2026-09-22"


@unittest.skipUnless(PACKAGE.exists(), "frozen RGIA probe package not built")
class FrozenRgiaProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "rgia_jstree_probe", PACKAGE / "run_probe.py"
        )
        cls.runner = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.runner)

    def test_five_gets_produce_one_candidate_record(self):
        runner = self.runner
        robots = (FIXTURES / "robots_RAW_bytes.txt").read_bytes()
        search_html = (FIXTURES / "live_WORKING_karta_kaluzhsk.html").read_bytes()
        calls = []

        class Response:
            def __init__(self, url, content=b"", payload=None, content_type="application/json"):
                self.url = url
                self.content = content
                self._payload = payload
                self.status_code = 200
                self.is_redirect = False
                self.headers = {"Content-Type": content_type}

            @property
            def text(self):
                return self.content.decode("utf-8", "replace")

            def json(self):
                return self._payload

        class Session:
            def get(self, url, params=None, timeout=None, allow_redirects=None):
                params = dict(params or {})
                calls.append((url, params, timeout, allow_redirects))
                if url == runner.ROBOTS:
                    return Response(url, robots, content_type="text/plain")
                if url == runner.SEARCH:
                    return Response(url, search_html, content_type="text/html")
                if url == runner.BASE + "/ajax/tree/112968" and params["id"] == "0":
                    return Response(url, payload=[{"id": "1050_0_74", "text": "Дела (74)"}])
                if url == runner.BASE + "/ajax/tree/112968":
                    return Response(url, payload=[{"id": None, "text": "1,1,1,2,4"}, {"id": "5191017", "text": "<div>дело 1</div>"}])
                if url == runner.BASE + "/ajax/obj/5191017/112968":
                    return Response(url, payload={"title": "Карта Калужской губернии", "attributes": [{"name": "Шифр", "text": "Ф. 1 Оп. 2 Д. 3"}, {"name": "Крайние даты", "text": "1864"}]})
                raise AssertionError((url, params))

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "probe"
            with patch.object(runner, "_session", return_value=Session()), patch.object(runner.time, "sleep"):
                attempt, code = runner.run(output=output)

            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 5)
            self.assertEqual(calls[0][0], runner.ROBOTS)
            self.assertEqual(calls[-1][0], runner.BASE + "/ajax/obj/5191017/112968")
            report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "probe_complete")
            self.assertEqual(report["records"], 1)
            self.assertFalse(report["ready_for_import"])
            request_log = json.loads((attempt / "requests.json").read_text(encoding="utf-8"))
            self.assertEqual(request_log["request_count"], 5)
            row = json.loads((attempt / "record.json").read_text(encoding="utf-8"))
            self.assertEqual(row["url"], "https://fgurgia.ru/object/5191017")
            self.assertEqual(row["year_from"], 1864)
            self.assertTrue((attempt / "records.csv").is_file())


if __name__ == "__main__":
    unittest.main()