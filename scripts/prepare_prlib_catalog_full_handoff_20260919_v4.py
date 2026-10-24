"""Собрать frozen-пакет ПрБ v4: единый конец, robots-cache и bounded transport retry."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/prlib_catalog_full_handoff_20260918_v3'
OUT=ROOT/'output/prlib_catalog_full_handoff_20260919_v4'
WORKING_OUTPUT=ROOT/'output/prlib_catalog_full_20260917_v1'
MODULES=('classify_stop.py','prlib_access.py','prlib_card.py','prlib_run_state.py','searcher_libraries.py')
HASH_FIELDS=('parser_sha256','access_sha256','detail_sha256')
def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def replace_once(text,old,new,label):
 if text.count(old)!=1:raise RuntimeError(f'Cannot apply v4 runner change {label!r}')
 return text.replace(old,new)
def state_hash_triples():
 triples=[]
 for path in sorted((WORKING_OUTPUT/'prlib_query_state').glob('*.json')):
  scope=json.loads(path.read_text(encoding='utf-8'))['scope'];triple={field:scope[field] for field in HASH_FIELDS}
  if any(not isinstance(value,str) or len(value)!=64 for value in triple.values()):raise ValueError(f'Invalid state hash in {path.name}')
  if triple not in triples:triples.append(triple)
 if not triples:raise ValueError('No preserved PRLIB query state for v4 migration whitelist')
 return triples
def runner_v4(source):
 source=replace_once(source,'"""Frozen PRLIB metadata collector v3. CLI has no scope overrides. No image fetching."""','"""Frozen PRLIB metadata collector v4. CLI has no scope overrides. No image fetching."""','header')
 source=replace_once(source,"      'collector_version':'20260918_v3','continuation_from_v1':continuation,","      'collector_version':'20260919_v4','continuation_from_v1':continuation,",'collector version')
 old=""" def guarded_raw(url):
  if not allowed_url(url,active['query'],cards):raise ValueError('URL outside catalog allowlist')
  if log['requests']>=scope['max_get_per_invocation']:raise BudgetStop()
  if getter is None and last[0] is not None:time.sleep(max(0,3-(time.monotonic()-last[0])))
  last[0]=time.monotonic();log['requests']+=1
  row={'id':log['requests'],'utc':utc(),'url':url,'event':'request_started'}
  durable_line(attempt/'requests.jsonl',row)
  try:
   response=raw(url)
   row.update(event='response',status=response[0],content_type=response[1],sha256=hashlib.sha256(response[2]).hexdigest())
   durable_line(attempt/'requests.jsonl',row)
   return response
  except Exception as exc:
   row.update(event='transport_error',error_type=type(exc).__name__)
   durable_line(attempt/'requests.jsonl',row);raise"""
 new=""" def guarded_raw(url):
  if not allowed_url(url,active['query'],cards):raise ValueError('URL outside catalog allowlist')
  backoff=(5,15)
  for wire_attempt in range(len(backoff)+1):
   if log['requests']>=scope['max_get_per_invocation']:raise BudgetStop()
   if getter is None and last[0] is not None:time.sleep(max(0,3-(time.monotonic()-last[0])))
   last[0]=time.monotonic();log['requests']+=1
   row={'id':log['requests'],'utc':utc(),'url':url,'event':'request_started','transport_attempt':wire_attempt+1}
   durable_line(attempt/'requests.jsonl',row)
   try:
    response=raw(url)
    row.update(event='response',status=response[0],content_type=response[1],sha256=hashlib.sha256(response[2]).hexdigest())
    durable_line(attempt/'requests.jsonl',row)
    return response
   except Exception as exc:
    row.update(event='transport_error',error_type=type(exc).__name__)
    durable_line(attempt/'requests.jsonl',row)
    if wire_attempt==len(backoff):raise
    durable_line(attempt/'requests.jsonl',{'utc':utc(),'url':url,'event':'transport_retry_scheduled','transport_attempt':wire_attempt+2,'backoff_seconds':backoff[wire_attempt]})
    time.sleep(backoff[wire_attempt])"""
 return replace_once(source,old,new,'bounded transport retry')
def instructions():return """# Полный проход метаданных ПрБ — пакет v4

Продолжение идёт в том же `output/prlib_catalog_full_20260917_v1`; scope, область, run_scope, JSONL/CSV и уже завершённые запросы не меняются вне штатного checkpoint.

1. Запусти только `python -B output/prlib_catalog_full_handoff_20260919_v4/run_catalog.py`.
2. Подтверждённый robots.txt кэшируется на время процесса (TTL 30 минут); policy, TLS, allowlist и crawl-delay >=3 с не меняются.
3. Транспортное исключение получает максимум две дополнительные попытки с 5 и 15 секундами backoff. HTTP, real_barrier, CAPTCHA, redirect-login, robots_disallow, unverified и незаверенные хеши не ретраятся.
4. Непагинированная страница с валидными /item/ и classify_stop=reported_end закрывается pager_reported_end. Пустая непроверенная выдача остаётся unverified.
5. Повторять команду разрешено только при exit_code=3 и stop_reason=request_budget; иначе передать REPORT без повтора.

`accepted_prior_module_hashes` содержит прежнюю v1-тройку и точную тройку из текущего state v3. Миграция разрешена только для этих троек при строгом сравнении прочих полей scope; чужая тройка — ValueError до сети.

Обход барьеров, авторизация, CAPTCHA, VPN/прокси, изображения/OCR, Notion и canonical-онтология не входят в запуск.
"""
def run_loop():return """$ErrorActionPreference = \"Continue\"
$root = \"D:\\Yandex.Disk\\History&Geography\\БД\\Поиск онлайн архив\"
Set-Location $root
$outDir = \"$root\\output\\prlib_catalog_full_20260917_v1\"
$maxCalls = 60
for ($i = 1; $i -le $maxCalls; $i++) {
    & python -B \"output/prlib_catalog_full_handoff_20260919_v4/run_catalog.py\"
    $code = $LASTEXITCODE
    if ($code -eq 0) { break }
    if ($code -ne 3) { break }
    $lastReport = Get-ChildItem \"$outDir\\attempts\" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName \"REPORT.json\" }
    if (-not $lastReport -or -not (Test-Path $lastReport)) { break }
    if ((Get-Content $lastReport -Raw -Encoding UTF8 | ConvertFrom-Json).stop_reason -ne \"request_budget\") { break }
    Start-Sleep -Seconds 5
}
"""
def main():
 if OUT.exists():raise SystemExit(f'Refusing to overwrite existing package: {OUT}')
 if not SOURCE.is_dir() or not WORKING_OUTPUT.is_dir():raise SystemExit('Missing v3 package or preserved working output')
 tests=subprocess.run([sys.executable,'-B','-m','pytest'],cwd=ROOT/'tests',text=True,capture_output=True)
 if tests.returncode:
  sys.stdout.write(tests.stdout);sys.stderr.write(tests.stderr);raise SystemExit('Local tests failed; v4 package was not created')
 source_manifest=json.loads((SOURCE/'manifest.json').read_text(encoding='utf-8'));accepted=list(source_manifest['continuation']['accepted_prior_module_hashes'])
 for triple in state_hash_triples():
  if triple not in accepted:accepted.append(triple)
 shutil.copytree(SOURCE,OUT,ignore=shutil.ignore_patterns('manifest.json','LOCAL_VALIDATION.json','run_loop_console.log'))
 frozen=OUT/'frozen/scripts/modules'
 for name in MODULES:shutil.copy2(ROOT/'scripts/modules'/name,frozen/name)
 (OUT/'run_catalog.py').write_text(runner_v4((SOURCE/'run_catalog.py').read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
 (OUT/'run_loop.ps1').write_text(run_loop(),encoding='utf-8',newline='\n')
 (OUT/'INSTRUCTIONS.md').write_text(instructions(),encoding='utf-8',newline='\n')
 project_files={p.relative_to(OUT/'frozen').as_posix():sha256(p) for p in sorted((OUT/'frozen').rglob('*')) if p.is_file()}
 package_files={p.relative_to(OUT).as_posix():sha256(p) for p in sorted(OUT.rglob('*')) if p.is_file() and 'frozen' not in p.parts}
 manifest={'project_files':project_files,'package_files':package_files,'dependencies':source_manifest['dependencies'],'continuation':{'prior_package':source_manifest['continuation']['prior_package'],'prior_manifest_sha256':source_manifest['continuation']['prior_manifest_sha256'],'working_output':'output/prlib_catalog_full_20260917_v1','scope_sha256':sha256(OUT/'scope.json'),'accepted_prior_module_hashes':accepted}}
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
 check=subprocess.run([sys.executable,'-B','-c',"import importlib.util; p=r'"+str(OUT/'run_catalog.py')+"'; s=importlib.util.spec_from_file_location('v4',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.verify())"],text=True,capture_output=True)
 if check.returncode or check.stdout.strip()!='True':
  shutil.rmtree(OUT);raise SystemExit('Frozen v4 verification failed: '+check.stderr+check.stdout)
 validation={'created_at_utc':datetime.now(timezone.utc).isoformat(),'network':'not_run','local_pytest_exit_code':tests.returncode,'local_pytest_summary':next((line.strip() for line in reversed(tests.stdout.splitlines()) if 'passed' in line),'unknown'),'frozen_verify':True,'manifest_sha256':sha256(OUT/'manifest.json'),'accepted_prior_module_hashes':accepted,'robots_cache_ttl_seconds':1800,'transport_retry_backoff_seconds':[5,15]}
 (OUT/'LOCAL_VALIDATION.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps(validation,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
