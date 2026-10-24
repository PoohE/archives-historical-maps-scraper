import unittest,json,tempfile,ast
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import prlib_access as access
import searcher_libraries as lib
from prlib_run_state import iter_query,query_path
from test_prlib_pagination import page
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"output/prlib_access_integration_20260915_v1"
ALLOW=(200,"text/plain",b"User-agent: *\nAllow: /","")
HTML=(200,"text/html",page(0,1,last=0).encode("utf-8"),"")
class AccessTests(unittest.TestCase):
 def setUp(self):access.reset_robots_cache()
 def fetch(self,responses,query="карта Калужской губернии",index=0):
  with patch.object(access,"raw_fetch",side_effect=responses) as raw,patch.object(access.time,"sleep"):
   value=access.fetch_page(query,index)
  return value,raw
 def blocked(self,responses,reason):
  with patch.object(access,"raw_fetch",side_effect=responses) as raw,patch.object(access.time,"sleep"):
   with self.assertRaises(access.AccessBlocked) as ctx:access.fetch_page("карта Калужской губернии",0)
  self.assertEqual(ctx.exception.reason,reason)
  self.assertLessEqual(raw.call_count,3)
  return ctx.exception.report,raw
 def test_legacy_missing_robots_reproduced(self):
  import requests,time
  src=(OUT/"before/scripts/modules/searcher_libraries.py").read_text(encoding="utf-8")
  tree=ast.parse(src);node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=="_get")
  ns={"requests":requests,"time":time,"UA":"test"}
  exec(compile(ast.Module(body=[node],type_ignores=[]),"old_get","exec"),ns)
  with patch.object(requests,"get",return_value=SimpleNamespace(raise_for_status=lambda:None)) as request,patch.object(time,"sleep"):
   ns["_get"](lib.PRLIB_SEARCH,params={"text":"test","page":0})
  self.assertEqual(request.call_count,1)
  self.assertEqual(request.call_args.args[0],lib.PRLIB_SEARCH)
 def test_allowed_redirect(self):
  response,raw=self.fetch([(301,"",b"",access.ROBOTS[1]),ALLOW,HTML])
  self.assertEqual(raw.call_count,3)
  self.assertTrue(response.url.startswith("https://www.prlib.ru/"))
  self.assertEqual(response.access_report["stop_reason"],"")
 def test_robots_denied(self):
  report,raw=self.blocked([(200,"text/plain",b"User-agent: *\nDisallow: /","")],"robots_disallow")
  self.assertEqual(raw.call_count,1)
 def test_robots_403(self):self.blocked([(403,"",b"","")],"robots_not_confirmed")
 def test_bad_redirect(self):
  report,raw=self.blocked([(301,"",b"","https://evil.test/?token=DUMMY")],"robots_redirect_outside_allowlist_or_loop")
  self.assertNotIn("DUMMY",json.dumps(report))
 def test_redirect_limit(self):self.blocked([(301,"",b"",access.ROBOTS[1]),(301,"",b"",access.ROBOTS[0])],"robots_redirect_limit")
 def test_search_redirect(self):
  self.blocked([ALLOW,(302,"",b"","https://www.prlib.ru/user/login")],"redirect_to_login")
 def test_captcha(self):self.blocked([ALLOW,(200,"text/html",b'<div class="h-captcha"></div>',"")],"captcha_widget")
 def test_password_is_only_an_informational_signal(self):
  body='<main><input type="password">По вашему запросу нет результатов</main>'.encode("utf-8")
  response,_=self.fetch([ALLOW,(200,"text/html",body,"")])
  verdict=response.access_report["classification"]
  self.assertEqual(verdict["verdict"],"reported_end")
  self.assertIn("login_form_present_ignored",verdict["signals"])
 def test_size_limit(self):self.blocked([ALLOW,(200,"text/html",b"x"*(access.LIMIT+1),"")],"response_too_large")
 def test_transport_error(self):self.blocked([TimeoutError()],"transport_error")
 def test_known_header_preserves_twenty_titles(self):
  raw=(ROOT/"output/prlib_dom_evidence_20260915_c3f8a2/main_sanitized.html").read_bytes()
  header=b'<header id="header"><div class="pane-prlib-login"><form id="user-login"><input type="password" id="edit-pass" name="pass" value="DUMMY"></form></div></header>'
  response,_=self.fetch([ALLOW,(200,"text/html",header+raw,"")],index=1)
  self.assertEqual(len(access.BeautifulSoup(response.text,"html.parser").select("article h2 a")),20)
  self.assertNotIn("DUMMY",response.text)
  verdict=response.access_report["classification"]
  self.assertEqual(verdict["verdict"],"more_pages")
  self.assertIn("login_form_present_ignored",verdict["signals"])
 def test_working_parser_access_each_page(self):
  responses=[ALLOW,(200,"text/html",page(0,1).encode(),""),
             (200,"text/html",page(1,2).encode(),"")]
  c={}
  with patch.object(access,"raw_fetch",side_effect=responses) as raw,patch.object(access.time,"sleep"),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
   rows=list(lib._search_prlib("карта Калужской губернии",None,None,3,coverage=c))
  self.assertEqual(raw.call_count,3);self.assertEqual(len(rows),2)
  self.assertEqual(len(c["access_pages"]),2);self.assertEqual(c["status"],"reported_end")
 def test_access_failure_saved_and_resumed(self):
  with tempfile.TemporaryDirectory(dir=OUT) as tmp:
   d=Path(tmp);c={};query="карта Калужской губернии"
   responses=[ALLOW,(200,"text/html",page(0,1).encode(),""),
              (200,"text/html",b'<div id="captcha"></div>',"")]
   with patch.object(access,"raw_fetch",side_effect=responses),patch.object(access.time,"sleep"),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
    with self.assertRaises(access.AccessBlocked):list(iter_query(d,"test",query,1700,1980,3,c))
   saved=json.loads(query_path(d,"test").read_text())
   self.assertEqual(saved["coverage"]["stop_reason"],"captcha_widget")
   self.assertEqual(saved["coverage"]["resume"]["page"],1)
   self.assertEqual(len(saved["coverage"]["access_pages"]),2)
   access.reset_robots_cache()
   with patch.object(access,"raw_fetch",side_effect=[ALLOW,(200,"text/html",page(1,2).encode(),"")]),patch.object(access.time,"sleep"),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
    rows=list(iter_query(d,"test",query,1700,1980,3,{}))
   saved=json.loads(query_path(d,"test").read_text())
   self.assertEqual(len(saved["previous_attempts"]),1)
   self.assertEqual(len(rows),1)
