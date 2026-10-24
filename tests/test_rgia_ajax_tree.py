"""Offline regression for the public RGIA jstree list route."""

import unittest
from pathlib import Path
from unittest.mock import patch

import searcher_rgia as rgia
import rgia_notion

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "output/rgia_fixtures_2026-09-22/live_WORKING_karta_kaluzhsk.html"


class Response:
    def __init__(self, text="", payload=None):
        self.text = text
        self.payload = [] if payload is None else payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if url == rgia.SEARCH_URL:
            return Response(FIXTURE.read_text(encoding="utf-8"))
        if url == rgia.TREE_URL.format("112968"):
            page = params["nPage"]
            if params["id"] == "0":
                return Response(payload=[{"id": "1050_0_74", "text": "Дела (74)"}])
            pages = {
                "1": [
                    {"id": None, "text": "1,1,1,2,2"},
                    {"id": "5191017", "text": "<div>дело 1</div>"},
                    {"id": "4844881", "text": "<div>дело 2</div>"},
                ],
                "2": [{"id": "5200000", "text": "<div>дело 3</div>"}],
            }
            return Response(payload=pages[page])
        if "/ajax/obj/" in url:
            object_id = url.split("/ajax/obj/")[1].split("/")[0]
            return Response(
                payload={
                    "title": "Дело " + object_id,
                    "attributes": [
                        {"name": "Шифр", "text": "Ф. 1 Оп. 1 Д. " + object_id[-1]},
                        {"name": "Крайние даты", "text": "1864"},
                    ],
                }
            )
        raise AssertionError(url)


class RgiaAjaxTreeTests(unittest.TestCase):
    def test_working_page_provides_the_live_search_index(self):
        self.assertEqual(
            rgia._extract_search_index(FIXTURE.read_text(encoding="utf-8")),
            "112968",
        )

    def test_terms_are_normalized_only_for_known_territories(self):
        self.assertEqual(
            rgia._rgia_search_terms("карта Калужская губерния"), "карта калужск"
        )
        self.assertEqual(rgia._rgia_search_terms("план Пермской"), "план пермск")
        self.assertEqual(
            rgia._rgia_search_terms("карта Петербурга"), "карта петербурга"
        )

    def test_tree_contract_is_not_the_pagination_endpoint(self):
        self.assertEqual(
            rgia._tree_params(2, "1050_0_74"),
            {
                "page": "1",
                "nPage": "2",
                "size": "",
                "id": "1050_0_74",
                "parentId": "",
                "objectType": "",
                "orderNumber": "0",
                "showPageList": "true",
                "count": "0",
                "alphabet": "",
                "tabId": "0",
                "completeWorkId": "-1",
            },
        )
        self.assertNotIn("/ajax/pages/", rgia.TREE_URL)

    def test_captured_detail_uses_zagolovok_for_title_and_candidate_mapping(self):
        raw = ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json"
        payload = __import__("json").loads(raw.read_text(encoding="utf-8"))
        record = rgia._parse_object_json(
            payload, "https://fgurgia.ru/object/5191017"
        )
        self.assertEqual(record.title, "Генеральная карта Калужского наместничества")
        self.assertEqual(record.fund_code, "Ф. 58 Оп. 3 Д. 312")
        self.assertEqual(record.year_from, 1900)
        self.assertEqual(record.year_to, 1900)
        candidate = rgia_notion.convert(record)
        self.assertEqual(
            candidate["Название источника"],
            "Генеральная карта Калужского наместничества",
        )
        self.assertEqual(candidate["Фонд"], "58")
        self.assertEqual(candidate["Опись"], "3")
        self.assertEqual(candidate["Единица хранения"], "312")
        self.assertEqual(candidate["Год создания (нижняя)"], 1900)
        self.assertEqual(candidate["Год создания (верхняя)"], 1900)
        self.assertIn("Шифр: Ф. 58 Оп. 3 Д. 312", candidate["Описание"])
        self.assertIn("Условная нормализация даты", candidate["Примечания"])

    def test_detail_preserves_raw_payload_and_explicit_scan_urls(self):
        payload = {
            "title": "Карта Калужской губернии",
            "downloadLink": "https://fgurgia.ru/files/123.pdf",
            "imageUrl": "https://fgurgia.ru/images/123.jp2",
            "attributes": [
                {"name": "Шифр", "text": "Ф. 1 Оп. 2 Д. 3"},
                {"name": "Крайние даты", "text": "1901"},
                {"name": "Нестандартное поле", "text": "сохранено без нормализации"},
            ],
        }
        record = rgia._parse_object_json(payload, "https://fgurgia.ru/object/123")
        candidate = rgia_notion.convert(record)
        self.assertEqual(record.raw_detail, payload)
        self.assertEqual(record.url_download, payload["downloadLink"])
        self.assertEqual(record.url_image, payload["imageUrl"])
        self.assertEqual(candidate["Путь / URL к файлу"], payload["downloadLink"])
        self.assertEqual(candidate["Прямая ссылка на файл изображения"], payload["imageUrl"])
        self.assertIn("Нестандартное поле: сохранено без нормализации", candidate["Описание"])

    def test_simple_search_expands_cases_and_uses_detail_json(self):
        session = Session()
        with patch("searcher_rgia.time.sleep"):
            records = list(rgia.search_simple(session, "карта Калужская губерния"))

        self.assertEqual(
            [record.url for record in records],
            [
                "https://fgurgia.ru/object/5191017",
                "https://fgurgia.ru/object/4844881",
                "https://fgurgia.ru/object/5200000",
            ],
        )
        self.assertEqual(records[0].fund_code, "Ф. 1 Оп. 1 Д. 7")
        self.assertEqual(records[0].year_from, 1864)
        search_call = next(call for call in session.calls if call[0] == rgia.SEARCH_URL)
        self.assertEqual(search_call[1]["p0.v"], "карта калужск")
        tree_calls = [call for call in session.calls if "/ajax/tree/" in call[0]]
        self.assertEqual(len(tree_calls), 4)
        self.assertFalse(any("/ajax/pages/" in call[0] for call in session.calls))


if __name__ == "__main__":
    unittest.main()
