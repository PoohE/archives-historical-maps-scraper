"""Build frozen PRLIB v6: resilient state writes and strict robots TTL refresh."""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/prlib_catalog_full_handoff_20260919_v5'
OUT=ROOT/'output/prlib_catalog_full_handoff_20260920_v6'
WORKING_OUTPUT=ROOT/'output/prlib_catalog_full_20260917_v1'
MODULES=('prlib_run_state.py','prlib_access.py','prlib_card.py')
HASH_FIELDS=('parser_sha256','access_sha256','detail_sha256')
def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def state_hash_triples():
 triples=[]
 for path in sorted((WORKING_OUTPUT/'prlib_query_state').glob('*.json')):
  scope=json.loads(path.read_text(encoding='utf-8'))['scope'];triple={field:scope[field] for field in HASH_FIELDS}
  if any(not isinstance(value,str) or len(value)!=64 for value in triple.values()):raise ValueError(f'Invalid state hash in {path.name}')
  if triple not in triples:triples.append(triple)
 if not triples:raise ValueError('No preserved PRLIB query state for v6 migration whitelist')
 return triples
def runner_v6(source):
 if source.count('"""Frozen PRLIB metadata collector v5. CLI has no scope overrides. No image fetching."""')!=1:raise RuntimeError('Cannot update v6 runner header')
 if source.count("'collector_version':'20260919_v5'")!=1:raise RuntimeError('Cannot update v6 collector version')
 return source.replace('"""Frozen PRLIB metadata collector v5. CLI has no scope overrides. No image fetching."""','"""Frozen PRLIB metadata collector v6. CLI has no scope overrides. No image fetching."""').replace("'collector_version':'20260919_v5'","'collector_version':'20260920_v6'")
def instructions():return """# Полный проход метаданных ПрБ — пакет v6

Это продолжение того же `output/prlib_catalog_full_20260917_v1`; scope, область, run_scope и уже завершённые запросы не меняются вне штатного checkpoint.

1. Запусти только `python -B output/prlib_catalog_full_handoff_20260920_v6/run_catalog.py`.
2. V6 сохраняет изоляцию аномалий одного запроса: `repeated_page`, pager-аномалии и локальная `unverified` выдача получают `partial`, `for_review=true` и запись в `REPORT.json:queries_for_review`; сохранённые строки не откатываются, следующий запрос продолжается.
3. `atomic_json` делает максимум 8 попыток с общим ожиданием менее 2 секунд только при `PermissionError` или WinError 5/32. После исчерпания исходная ошибка остаётся фатальной; другие ошибки не ретраятся.
4. TTL-обновление robots принимает только единственный точный redirect `https://prlib.ru/robots.txt` → `https://www.prlib.ru/robots.txt`; иной или второй redirect останавливает прогон. Барьеры не обходятся.
5. `real_barrier`, CAPTCHA, redirect-login, robots, транспорт после retry, request_budget, незаверенные хеши и JSONL/CSV mismatch остаются фатальными. Лимит глубины не включён; REPORT сохраняет глубину каждого запроса.

`accepted_prior_module_hashes` содержит v1, v3, v4 и фактическую v5-тройку из текущего state. Миграция возможна только для этих троек; чужая тройка — ValueError до сети.

Авторизация, CAPTCHA, VPN/прокси, изображения/OCR, Notion и canonical-онтология не входят в запуск.
"""
def run_loop(source):
 return source.replace('prlib_catalog_full_handoff_20260919_v5','prlib_catalog_full_handoff_20260920_v6')
def main():
 if OUT.exists():raise SystemExit(f'Refusing to overwrite existing package: {OUT}')
 if not SOURCE.is_dir() or not WORKING_OUTPUT.is_dir():raise SystemExit('Missing v5 package or preserved working output')
 tests=subprocess.run([sys.executable,'-B','-m','pytest'],cwd=ROOT/'tests',text=True,capture_output=True)
 if tests.returncode:
  sys.stdout.write(tests.stdout);sys.stderr.write(tests.stderr);raise SystemExit('Local tests failed; v6 package was not created')
 source_manifest=json.loads((SOURCE/'manifest.json').read_text(encoding='utf-8'));accepted=list(source_manifest['continuation']['accepted_prior_module_hashes'])
 for triple in state_hash_triples():
  if triple not in accepted:accepted.append(triple)
 shutil.copytree(SOURCE,OUT,ignore=shutil.ignore_patterns('manifest.json','LOCAL_VALIDATION.json','run_loop_console.log'))
 frozen=OUT/'frozen/scripts/modules'
 for name in MODULES:shutil.copy2(ROOT/'scripts/modules'/name,frozen/name)
 (OUT/'run_catalog.py').write_text(runner_v6((SOURCE/'run_catalog.py').read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
 (OUT/'run_loop.ps1').write_text(run_loop((SOURCE/'run_loop.ps1').read_text(encoding='utf-8')),encoding='utf-8',newline='\n')
 (OUT/'INSTRUCTIONS.md').write_text(instructions(),encoding='utf-8',newline='\n')
 project_files={p.relative_to(OUT/'frozen').as_posix():sha256(p) for p in sorted((OUT/'frozen').rglob('*')) if p.is_file()}
 package_files={p.relative_to(OUT).as_posix():sha256(p) for p in sorted(OUT.rglob('*')) if p.is_file() and 'frozen' not in p.parts}
 manifest={'project_files':project_files,'package_files':package_files,'dependencies':source_manifest['dependencies'],'continuation':{'prior_package':source_manifest['continuation']['prior_package'],'prior_manifest_sha256':source_manifest['continuation']['prior_manifest_sha256'],'working_output':'output/prlib_catalog_full_20260917_v1','scope_sha256':sha256(OUT/'scope.json'),'accepted_prior_module_hashes':accepted}}
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
 check=subprocess.run([sys.executable,'-B','-c',"import importlib.util; p=r'"+str(OUT/'run_catalog.py')+"'; s=importlib.util.spec_from_file_location('v6',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.verify())"],text=True,capture_output=True)
 if check.returncode or check.stdout.strip()!='True':
  shutil.rmtree(OUT);raise SystemExit('Frozen v6 verification failed: '+check.stderr+check.stdout)
 validation={'created_at_utc':datetime.now(timezone.utc).isoformat(),'network':'not_run','local_pytest_exit_code':tests.returncode,'local_pytest_summary':next((line.strip() for line in reversed(tests.stdout.splitlines()) if 'passed' in line),'unknown'),'frozen_verify':True,'manifest_sha256':sha256(OUT/'manifest.json'),'accepted_prior_module_hashes':accepted,'atomic_json_retry':{'attempts':8,'retryable':['PermissionError','WinError 5','WinError 32'],'total_backoff_seconds':1.95},'robots_ttl_redirect':'only exact prlib.ru robots -> www.prlib.ru robots','query_local_review_reasons':['repeated_page','pager_missing','current_page_mismatch','invalid_pager_link','pager_label_mismatch','next_page_not_linked','empty_unverified'],'depth_cap':'not_enabled','depth_metric':'coverage.max_page'}
 (OUT/'LOCAL_VALIDATION.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
 print(json.dumps(validation,ensure_ascii=False,indent=2))
if __name__=='__main__':main()