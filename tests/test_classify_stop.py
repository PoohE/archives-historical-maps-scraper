"""Тесты classify_stop: конец выдачи vs настоящий барьер.

Главная регрессия -- fixtures/prlib_search_empty_tail_20260918.html: подлинный
пустой «хвост» выдачи ПрБ (сырой HTTP 200, «По вашему запросу нет результатов»,
password-поле шапки на месте), на котором prlib_access.barrier_diagnostics дал
ложный authentication_or_login_form_unresolved (прогон prlib_catalog_full_20260917_v1,
attempt 20260918_004617_fda1526c, 131 GET, 1/294). Классификатор обязан дать
reported_end, зафиксировав форму логина информационным сигналом.
"""
import unittest
from pathlib import Path
import classify_stop as cs

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests"/"fixtures"/"prlib_search_empty_tail_20260918.html"
ATTEMPT=ROOT/"output"/"prlib_catalog_full_20260917_v1"/"attempts"/"20260918_004617_fda1526c"
EMPTY_TAIL_URL="https://www.prlib.ru/collections/467000/search?text=%D0%BF%D0%BB%D0%B0%D0%BD&page=16"

def page(items=1,next_link=True,marker="",extra=""):
 body="".join(f'<article><h2><a href="/item/{i}">Карта {i}</a></h2></article>' for i in range(1,items+1))
 pager='<ul class="pagination"><li><a href="/collections/467000/search?text=x&page=1">2</a></li></ul>' if next_link else ""
 return f"<html><body><main>{body}{marker}{pager}</main>{extra}</body></html>"

class ClassifyStopTests(unittest.TestCase):
 def classify(self,body,status=200,url="",location=""):
  return cs.classify_response(status,"text/html; charset=utf-8",body,url=url,redirect_location=location)

 @unittest.skipUnless(FIXTURE.exists(),"фикстура пустого хвоста не захвачена")
 def test_real_empty_tail_is_reported_end_not_barrier(self):
  v=self.classify(FIXTURE.read_bytes(),url=EMPTY_TAIL_URL)
  self.assertEqual(v["verdict"],cs.REPORTED_END)
  self.assertEqual(v["reason"],"empty_with_end_marker")
  self.assertIn("login_form_present_ignored",v["signals"])  # форма замечена, но не решает
  self.assertEqual(v["evidence"]["items"],0)

 def test_results_with_next(self):
  v=self.classify(page(items=2,next_link=True),url="https://x/search?page=0")
  self.assertEqual(v["verdict"],cs.MORE_PAGES)

 def test_last_page_without_next(self):
  v=self.classify(page(items=2,next_link=False),url="https://x/search?page=5")
  self.assertEqual((v["verdict"],v["reason"]),(cs.REPORTED_END,"last_page_no_next"))

 def test_empty_without_marker_is_ambiguous(self):
  v=self.classify(page(items=0,next_link=False))
  self.assertEqual((v["verdict"],v["reason"]),(cs.AMBIGUOUS_EMPTY,"empty_without_end_marker"))

 def test_login_form_alone_never_decides(self):
  extra='<header id="header"><form id="user-login"><input type="password" id="edit-pass"></form></header>'
  v=self.classify(page(items=2,next_link=True,extra=extra),url="https://x/search?page=0")
  self.assertEqual(v["verdict"],cs.MORE_PAGES)
  self.assertIn("login_form_present_ignored",v["signals"])

 def test_http_auth_statuses_are_barriers(self):
  for status in (401,403,429):
   self.assertEqual(self.classify(b"",status=status)["verdict"],cs.REAL_BARRIER)

 def test_redirect_to_login_is_barrier_other_redirect_is_transport(self):
  v=self.classify(b"",status=302,location="https://www.prlib.ru/user/login?dest=x")
  self.assertEqual((v["verdict"],v["reason"]),(cs.REAL_BARRIER,"redirect_to_login"))
  v=self.classify(b"",status=302,location="https://www.prlib.ru/other")
  self.assertEqual(v["verdict"],cs.TRANSPORT_ERROR)

 def test_captcha_and_barrier_phrase(self):
  v=self.classify('<html><body><div class="g-recaptcha"></div></body></html>')
  self.assertEqual((v["verdict"],v["reason"]),(cs.REAL_BARRIER,"captcha_widget"))
  v=self.classify("<html><body><main>Требуется авторизация</main></body></html>")
  self.assertEqual((v["verdict"],v["reason"]),(cs.REAL_BARRIER,"barrier_phrase"))

 def test_exception_is_transport(self):
  self.assertEqual(cs.classify_exception(TimeoutError("x"))["verdict"],cs.TRANSPORT_ERROR)

 @unittest.skipUnless(ATTEMPT.exists(),"каталог попытки прогона недоступен")
 def test_sweep_saved_attempt_pages_no_false_barriers(self):
  pages=sorted(ATTEMPT.glob("*.search.sanitized.html"))
  self.assertTrue(pages)
  for f in pages:
   v=self.classify(f.read_bytes())
   self.assertIn(v["verdict"],(cs.MORE_PAGES,cs.REPORTED_END),f.name)

if __name__=="__main__":
 unittest.main()
