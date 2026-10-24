import unittest,json
from pathlib import Path
from unittest.mock import patch
import prlib_card as card
import prlib_access as access
import searcher_libraries as lib
from test_prlib_pagination import page
ROOT=Path(__file__).resolve().parents[1]
ALLOW=(200,'text/plain',b'User-agent: *\nAllow: /','')
URL='https://prlib.ru/item/426814'
class DetailTests(unittest.TestCase):
 def setUp(self):access.reset_robots_cache()
 @classmethod
 def setUpClass(cls):
  cls.body=(ROOT/'output/prlib_review_20260911/evidence_www/426814.html').read_bytes()
 def run_card(self,items):
  with patch.object(access,'raw_fetch',side_effect=items) as get,patch.object(card.time,'sleep') as pause:
   result=card.fetch_card(URL)
  return result,get,pause
 def blocked(self,items,reason):
  with patch.object(access,'raw_fetch',side_effect=items) as get,patch.object(card.time,'sleep'):
   with self.assertRaises(access.AccessBlocked) as ctx:card.fetch_card(URL)
  self.assertEqual(ctx.exception.reason,reason)
  self.assertLessEqual(get.call_count,2)
  return ctx.exception.report,get
 def test_real_card_fields_and_sanitization(self):
  rec,get,pause=self.run_card([ALLOW,(200,'text/html',self.body,'')])
  prior=card.parse_card(self.body,URL)
  for key in ('title','author','year_from','year_to','place','description'):
   self.assertEqual(rec[key],prior[key])
  self.assertEqual(rec['extra']['gallery_urls'],prior['extra']['gallery_urls'])
  self.assertNotIn('<script',rec['extra']['raw_detail_html'])
  self.assertNotIn('<input',rec['extra']['raw_detail_html'])
  self.assertEqual(get.call_count,2)
  self.assertEqual(len(rec['extra']['detail_access']['requests']),2)
  self.assertEqual(rec['extra']['detail_access']['status'],'parsed_candidate')
 def test_fresh_robots_each_card(self):
  with patch.object(access,'raw_fetch',side_effect=[ALLOW,(200,'text/html',self.body,''),(200,'text/html',self.body,'')]) as get,patch.object(card.time,'sleep'):
   card.fetch_card(URL);card.fetch_card(URL)
  self.assertEqual([x.args[0] for x in get.call_args_list].count('https://prlib.ru/robots.txt'),1)
 def test_detail_redirect_not_followed(self):
  report,get=self.blocked([ALLOW,(302,'',b'','https://www.prlib.ru/user/login?token=DUMMY')],'http_error_or_redirect')
  self.assertEqual(get.call_count,2);self.assertNotIn('DUMMY',json.dumps(report))
 def test_robots_redirect_not_followed(self):
  _,get=self.blocked([(301,'',b'','https://prlib.ru/robots.txt')],'robots_redirect_outside_allowlist_or_loop')
  self.assertEqual(get.call_count,1)
 def test_robots_ttl_refresh_follows_allowlisted_redirect(self):
  responses=[ALLOW,(200,'text/html',self.body,''),(301,'',b'',access.ROBOTS[1]),ALLOW,(200,'text/html',self.body,'')]
  with patch.object(access,'raw_fetch',side_effect=responses) as get,patch.object(card.time,'sleep'),patch.object(access.time,'monotonic',side_effect=[0,0,access.ROBOTS_TTL_SECONDS+1,access.ROBOTS_TTL_SECONDS+1]):
   first=card.fetch_card(URL);second=card.fetch_card(URL)
  self.assertEqual(get.call_count,5)
  self.assertEqual([call.args[0] for call in get.call_args_list][2:4],list(access.ROBOTS))
  self.assertEqual(first['extra']['detail_access']['robots_cache'],'miss')
  self.assertEqual(second['extra']['detail_access']['robots_cache'],'miss')
  self.assertEqual(second['extra']['detail_access']['requests'][0]['allowed_redirect'],access.ROBOTS[1])
 def test_robots_second_redirect_is_blocked_by_policy(self):
  _,get=self.blocked([(301,'',b'',access.ROBOTS[1]),(301,'',b'',access.ROBOTS[0])],'robots_redirect_limit')
  self.assertEqual(get.call_count,2)
 def test_denied(self):
  _,get=self.blocked([(200,'text/plain',b'User-agent: *\nDisallow: /','')],'robots_disallow')
  self.assertEqual(get.call_count,1)
 def test_bad_robots(self):self.blocked([(200,'text/plain',b'not robots','')],'robots_not_confirmed')
 def test_captcha(self):self.blocked([ALLOW,(200,'text/html',b'<div class="h-captcha"></div>','')],'captcha_widget')
 def test_password_is_not_a_barrier(self):
  report,_=self.blocked([ALLOW,(200,'text/html',b'<input type="password">','')],'card_parser_error')
  self.assertIn('login_form_present_ignored',report['classification']['signals'])
 def test_oversize(self):self.blocked([ALLOW,(200,'text/html',b'x'*(access.LIMIT+1),'')],'response_too_large')
 def test_timeout(self):self.blocked([ALLOW,TimeoutError('DUMMY')],'transport_error')
 def test_non_html(self):self.blocked([ALLOW,(200,'application/pdf',b'%PDF','')],'unexpected_content_type')
 def test_parse_error(self):self.blocked([ALLOW,(200,'text/html',b'<main>no card</main>','')],'card_parser_error')
 def test_long_delay(self):self.blocked([(200,'text/plain',b'User-agent: *\nAllow: /\nCrawl-delay: 61','')],'robots_delay_requires_rescheduling')
 def test_delay_respected(self):
  _,_,pause=self.run_card([(200,'text/plain',b'User-agent: *\nAllow: /\nCrawl-delay: 7',''),(200,'text/html',self.body,'')])
  self.assertEqual([x.args[0] for x in pause.call_args_list],[7])
 def test_invalid_input_no_network(self):
  with patch.object(access,'raw_fetch') as get:
   with self.assertRaises(ValueError):card.fetch_card('https://www.prlib.ru/user/login')
  get.assert_not_called()
 def test_detail_failure_preserves_reason_in_search(self):
  coverage={}
  responses=[ALLOW,(200,'text/html',page(0,426814,last=0).encode(),''),(200,'text/html',b'<div id="captcha"></div>','')]
  with patch.object(access,'raw_fetch',side_effect=responses),patch.object(card.time,'sleep'),patch.object(lib,'PRLIB_FETCH_DETAILS_IN_BULK',True):
   with self.assertRaises(access.AccessBlocked):list(lib._search_prlib('карта Калужской губернии',None,None,1,coverage=coverage))
  self.assertEqual(coverage['stop_reason'],'captcha_widget')
  self.assertEqual(len(coverage['detail_access_failures']),1)
  self.assertEqual(coverage['resume']['page'],0)
