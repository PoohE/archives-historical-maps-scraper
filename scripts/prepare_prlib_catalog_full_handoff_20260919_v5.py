"""Собрать frozen-пакет ПрБ v5: изоляция query-local аномалий без обхода барьеров."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/prlib_catalog_full_handoff_20260919_v4'
OUT=ROOT/'output/prlib_catalog_full_handoff_20260919_v5'
WORKING_OUTPUT=ROOT/'output/prlib_catalog_full_20260917_v1'
MODULES=('searcher_libraries.py',)
HASH_FIELDS=('parser_sha256','access_sha256','detail_sha256')
def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def replace_once(text,old,new,label):
 if text.count(old)!=1:raise RuntimeError(f'Cannot apply v5 runner change {label!r}')
 return text.replace(old,new)
def replace_between(text,start,end,new,label):
 if text.count(start)!=1 or text.count(end)!=1:raise RuntimeError(f'Cannot locate v5 runner change {label!r}')
 a=text.index(start);b=text.index(end,a)
 if b<0:raise RuntimeError(f'Cannot order v5 runner change {label!r}')
 return text[:a]+new+text[b:]
def state_hash_triples():
 triples=[]
 for path in sorted((WORKING_OUTPUT/'prlib_query_state').glob('*.json')):
  scope=json.loads(path.read_text(encoding='utf-8'))['scope'];triple={field:scope[field] for field in HASH_FIELDS}
  if any(not isinstance(value,str) or len(value)!=64 for value in triple.values()):raise ValueError(f'Invalid state hash in {path.name}')
  if triple not in triples:triples.append(triple)
 if not triples:raise ValueError('No preserved PRLIB query state for v5 migration whitelist')
 return triples
def runner_v5(source):
 source=replace_once(source,'"""Frozen PRLIB metadata collector v4. CLI has no scope overrides. No image fetching."""','"""Frozen PRLIB metadata collector v5. CLI has no scope overrides. No image fetching."""','header')
 source=replace_once(source,"      'collector_version':'20260919_v4','continuation_from_v1':continuation,","      'collector_version':'20260919_v5','continuation_from_v1':continuation,",'collector version')
 old=""" def deny(*a,**kw):raise RuntimeError('Only guarded catalog urllib GET permitted')
 rc=2;cov={}
 with ExitStack() as stack:"""
 new=""" def deny(*a,**kw):raise RuntimeError('Only guarded catalog urllib GET permitted')
 def query_rows(territory,keyword):
  return sum(source=='prlib' and saved_territory==territory and saved_keyword==keyword for source,saved_territory,saved_keyword,_ in keys)
 def persist_review(key,cov):
  path=query_path(out,key)
  if not path.exists():raise ValueError('Missing state for query review')
  record=json.loads(path.read_text(encoding='utf-8'))
  record['coverage']=dict(cov)
  atomic_json(path,record)
 def review_item(key,territory,keyword,cov):
  return {'key':key,'territory':territory,'keyword':keyword,'stop_reason':cov.get('stop_reason','unverified_coverage'),
          'resume_page':cov.get('resume',{}).get('page'),'rows_collected':query_rows(territory,keyword),
          'max_page':cov.get('max_page')}
 rc=2;cov={};queries_for_review=[]
 with ExitStack() as stack:"""
 source=replace_once(source,old,new,'review helpers')
 start="""  try:
   for territory,keyword,key in queries:
"""
 end="""  except BudgetStop:"""
 body="""  try:
   for territory,keyword,key in queries:
    active['query']=keyword+' '+territory
    while not completed_query(out,key,scope['year_from'],scope['year_to']):
     cov={};iterator=iter_query(out,key,active['query'],scope['year_from'],scope['year_to'],1,cov)
     try:
      for rec in iterator:
       ident=identity('prlib',territory,keyword,rec.url)
       if ident in keys:continue
       if rec.extra.get('detail_access',{}).get('status')!='parsed_candidate':raise ValueError('Detail evidence missing')
       row={'source':'prlib','territory':territory,'keyword':keyword,'record':asdict(rec)}
       durable_line(out/'records_full.jsonl',row)
       values=['prlib',territory,keyword,rec.title,rec.year_from,rec.year_to,rec.url,rec.description or '']
       positive=classify(rec.title)=='positive';dest='search_audit.csv' if positive else 'review.csv'
       with (out/dest).open('a',encoding='utf-8',newline='') as f:
        csv.writer(f).writerow(values if positive else values+['','']);f.flush();os.fsync(f.fileno())
       keys.add(ident)
     except lib.PrLibIncompleteSearch:
      if cov.get('stop_reason')!='page_limit' and not cov.get('for_review'):raise
     finally:iterator.close()
     existing_outputs(out)
     if cov.get('status')=='reported_end':
      if log['requests']>=scope['max_get_per_invocation']:raise BudgetStop()
      continue
     if cov.get('stop_reason')=='page_limit':
      if log['requests']>=scope['max_get_per_invocation']:raise BudgetStop()
      continue
     if cov.get('for_review') or cov.get('status')=='unverified':
      cov.update(status='partial',for_review=True,full_search_complete=False)
      persist_review(key,cov)
      item=review_item(key,territory,keyword,cov);queries_for_review.append(item)
      durable_line(attempt/'requests.jsonl',{'utc':utc(),'event':'query_for_review',**item})
      break
     log['stop_reason']=cov.get('stop_reason') or 'unverified_coverage';raise RuntimeError('Unverified coverage')
   if queries_for_review:log.update(status='query_scope_review',stop_reason='')
   else:log.update(status='query_scope_completed',stop_reason='')
   rc=0
"""
 source=replace_between(source,start,end,body,'query-local isolation')
 old_final="""    coverage=[]
    for territory,keyword,key in queries:
     p=query_path(out,key)
     state=json.loads(p.read_text(encoding='utf-8'))['coverage'] if p.exists() else {}
     verdicts=state.get('classifier_verdicts',[])
     last_verdict=verdicts[-1] if verdicts else {}
     coverage.append({'key':key,'status':state.get('status','not_started'),'stop_reason':state.get('stop_reason',''),'resume_page':state.get('resume',{}).get('page'),'classifier_verdict':last_verdict.get('verdict',''),'classifier_reason':last_verdict.get('reason','')})
    atomic_json(attempt/'coverage.json',coverage)
    done=sum(x['status']=='reported_end' for x in coverage)
    log.update(total_queries=len(queries),completed_queries=done,query_scope_complete=done==len(queries),hashes_after=verify(),frozen_modules_verified=True)
    if done==len(queries) and log['stop_reason']=='request_budget':log.update(status='query_scope_completed',stop_reason='');rc=0
"""
 new_final="""    coverage=[]
    query_lookup={key:(territory,keyword) for territory,keyword,key in queries}
    for territory,keyword,key in queries:
     p=query_path(out,key)
     state=json.loads(p.read_text(encoding='utf-8'))['coverage'] if p.exists() else {}
     verdicts=state.get('classifier_verdicts',[])
     last_verdict=verdicts[-1] if verdicts else {}
     coverage.append({'key':key,'status':state.get('status','not_started'),'stop_reason':state.get('stop_reason',''),'resume_page':state.get('resume',{}).get('page'),'for_review':bool(state.get('for_review')),'max_page':state.get('max_page'),'classifier_verdict':last_verdict.get('verdict',''),'classifier_reason':last_verdict.get('reason','')})
    review_by_key={item['key']:item for item in queries_for_review}
    for item in coverage:
     if item['for_review'] and item['key'] not in review_by_key:
      territory,keyword=query_lookup[item['key']]
      review_by_key[item['key']]={'key':item['key'],'territory':territory,'keyword':keyword,'stop_reason':item['stop_reason'],'resume_page':item['resume_page'],'rows_collected':query_rows(territory,keyword),'max_page':item['max_page']}
    queries_for_review=list(review_by_key.values())
    atomic_json(attempt/'coverage.json',coverage)
    done=sum(x['status']=='reported_end' for x in coverage)
    review_state=[x for x in coverage if x['for_review']]
    log.update(total_queries=len(queries),completed_queries=done,review_queries=len(review_state),queries_for_review=queries_for_review,not_started_queries=sum(x['status']=='not_started' for x in coverage),query_depths={x['key']:x['max_page'] for x in coverage if x['max_page'] is not None},query_scope_complete=done==len(queries) and not review_state,hashes_after=verify(),frozen_modules_verified=True)
    if done==len(queries) and not review_state and log['stop_reason']=='request_budget':log.update(status='query_scope_completed',stop_reason='');rc=0
"""
 source=replace_once(source,old_final,new_final,'report review/depth fields')
 return source
def instructions():return """# Полный проход метаданных ПрБ — пакет v5

Это продолжение того же `output/prlib_catalog_full_20260917_v1`; scope, область, run_scope и уже завершённые запросы не меняются вне штатного checkpoint.

1. Запусти только `python -B output/prlib_catalog_full_handoff_20260919_v5/run_catalog.py`.
2. V5 отделяет аномалию одного запроса от состояния сайта: `repeated_page`, pager-аномалии и локальная `unverified` выдача получают `partial`, `for_review=true` и запись в `REPORT.json:queries_for_review`; сохранённые строки не откатываются, следующий запрос продолжается.
3. `real_barrier`, CAPTCHA, redirect-login, robots, транспорт после 5/15-секундных retry, request_budget, незаверенные хеши и JSONL/CSV mismatch остаются фатальными. Барьеры не обходятся.
4. `repeated_page` не является концом выдачи. Он остаётся review, с resume и причиной. REPORT включает глубину `max_page` каждого запроса; лимит глубины не включён.
5. Exit 0 со статусом `query_scope_review` не означает полный каталог: его список review передаётся человеку. Автопродолжение допустимо только при exit 3 / `request_budget`.

`accepted_prior_module_hashes` содержит v1, v3 и фактическую v4-тройку из текущего state. Миграция возможна только для этих троек; чужая тройка — ValueError до сети.

Авторизация, CAPTCHA, VPN/прокси, изображения/OCR, Notion и canonical-онтология не входят в запуск.
"""
def run_loop(source):
 return source.replace('prlib_catalog_full_handoff_20260919_v4','prlib_catalog_full_handoff_20260919_v5')
def main():
 if OUT.exists():raise SystemExit(f'Refusing to overwrite existing package: {OUT}')
 if not SOURCE.is_dir() or not WORKING_OUTPUT.is_dir():raise SystemExit('Missing v4 package or preserved working output')
 tests=subprocess.run([sys.executable,'-B','-m','pytest'],cwd=ROOT/'tests',text=True,capture_output=True)
 if tests.returncode:
  sys.stdout.write(tests.stdout);sys.stderr.write(tests.stderr);raise SystemExit('Local tests failed; v5 package was not created')
 source_manifest=json.loads((SOURCE/'manifest.json').read_text(encoding='utf-8'));accepted=list(source_manifest['continuation']['accepted_prior_module_hashes'])
 for triple in state_hash_triples():
  if triple not in accepted:accepted.append(triple)
 shutil.copytree(SOURCE,OUT,ignore=shutil.ignore_patterns('manifest.json','LOCAL_VALIDATION.json','run_loop_console.log'))
 frozen=OUT/'frozen/scripts/modules'
 for name in MODULES:shutil.copy2(ROOT/'scripts/modules'/name,frozen/name)
 (OUT/'run_catalog.py').write_text(runner_v5((SOURCE/'run_catalog.py').read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
 (OUT/'run_loop.ps1').write_text(run_loop((SOURCE/'run_loop.ps1').read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
 (OUT/'INSTRUCTIONS.md').write_text(instructions(),encoding='utf-8',newline='\n')
 project_files={p.relative_to(OUT/'frozen').as_posix():sha256(p) for p in sorted((OUT/'frozen').rglob('*')) if p.is_file()}
 package_files={p.relative_to(OUT).as_posix():sha256(p) for p in sorted(OUT.rglob('*')) if p.is_file() and 'frozen' not in p.parts}
 manifest={'project_files':project_files,'package_files':package_files,'dependencies':source_manifest['dependencies'],'continuation':{'prior_package':source_manifest['continuation']['prior_package'],'prior_manifest_sha256':source_manifest['continuation']['prior_manifest_sha256'],'working_output':'output/prlib_catalog_full_20260917_v1','scope_sha256':sha256(OUT/'scope.json'),'accepted_prior_module_hashes':accepted}}
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
 check=subprocess.run([sys.executable,'-B','-c',"import importlib.util; p=r'"+str(OUT/'run_catalog.py')+"'; s=importlib.util.spec_from_file_location('v5',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.verify())"],text=True,capture_output=True)
 if check.returncode or check.stdout.strip()!='True':
  shutil.rmtree(OUT);raise SystemExit('Frozen v5 verification failed: '+check.stderr+check.stdout)
 validation={'created_at_utc':datetime.now(timezone.utc).isoformat(),'network':'not_run','local_pytest_exit_code':tests.returncode,'local_pytest_summary':next((line.strip() for line in reversed(tests.stdout.splitlines()) if 'passed' in line),'unknown'),'frozen_verify':True,'manifest_sha256':sha256(OUT/'manifest.json'),'accepted_prior_module_hashes':accepted,'query_local_review_reasons':['repeated_page','pager_missing','current_page_mismatch','invalid_pager_link','pager_label_mismatch','next_page_not_linked','empty_unverified'],'depth_cap':'not_enabled','depth_metric':'coverage.max_page'}
 (OUT/'LOCAL_VALIDATION.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps(validation,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

