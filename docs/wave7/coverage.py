#!/usr/bin/env python3
"""Trace touched batteries and changed protocol tokens to real gate job bodies."""
import ast,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];tests=ROOT/'tests';gate=(tests/'gate.sh').read_text()
blocks={m[1]:m[2] for m in re.finditer(r'^([A-Za-z0-9_]+)\(\)\{\n(.*?)(?=^}\n)',gate,re.M|re.S)}
files={p.name:p for p in tests.glob('*.py')};deps={};catalog={}
for base in (tests,ROOT/'tools'):
 for p in base.rglob('*'):
  if p.is_file() and p.suffix in ('.py','.cc','.inc','.sh'):
   catalog.setdefault(p.name,[]).append(p)
for name,paths in catalog.items():
 deps[name]=set()
 for p in paths:
  body=p.read_text(errors='replace')
  # Include explicit subprocess scripts, with_name fixtures and C++ check includes,
  # in addition to imports. Same-basename files are conservatively unioned.
  deps[name].update(x for x in re.findall(r'\b([A-Za-z0-9_]+\.(?:py|cc|inc|sh))\b',body) if x in catalog and x not in (name,'gate.sh'))
  if p.suffix!='.py':continue
  try:t=ast.parse(body)
  except SyntaxError:continue
  deps[name].update(x+'.py' for n in ast.walk(t) for x in ([n.module.split('.')[0]] if isinstance(n,ast.ImportFrom) and n.module else [a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else []) if x+'.py' in catalog)
def closure(names):
 out=set(names);todo=list(names)
 while todo:
  for n in deps.get(todo.pop(),set())-out:out.add(n);todo.append(n)
 return out
jobfiles={n:closure(set(re.findall(r'(?:tests|tools)/([A-Za-z0-9_]+\.(?:py|cc|sh|inc))',b))) for n,b in blocks.items()}
# Shell variable-driven battery lists and linked C++ unit entry points are not
# literal tests/foo.py invocations. Resolve these explicitly, then propagate
# helper calls. Keep these mappings reviewable rather than claiming an AST
# parser understands shell expansion or the Makefile's implicit rules.
feature=re.search(r'^FEATURE_BATTERIES="([^"]+)"',gate,re.M)[1].split()
for name in ('feature_split_job','feature_armed_job'):
 jobfiles[name].update(closure({x+'.py' for x in feature}))
for name,body in blocks.items():
 for words in re.findall(r'for (?:t|test) in ([A-Za-z0-9_ ]+); do',body):
  jobfiles[name].update(closure({x+'.py' for x in words.split() if x+'.py' in files}))
units={
 'atomic-survivors-unit':['atomic_survivors_unit.cc','txnorder_checks.inc'],
 'exbatch-unit':['exbatch_unit.cc'], 'exbatch-db0-unit':['exbatch_unit.cc'],
 'multidb-unit':['multidb_unit.cc'], 'multidb-boundary-unit':['multidb_boundary_unit.cc'],
 'netcmd-unit':['netcmd_unit.cc','netcmd_stream_unit.cc','netcmd_zset_unit.cc','netcmd_config_unit.cc'],
 'store-regression':['store_regression.cc'],
 'at15-unit':['at15_unit.cc'], 'at15-db0-unit':['at15_unit.cc'],
 'shutdown-unit':['shutdown_unit.cc','shutdown_client_checks.inc'],
 'core-concurrency-unit':['core_concurrency_unit.cc','slowlog_completion_checks.inc','wave5_dispatch_checks.inc'],
 'execabort-watch-unit':['execabort_watch_unit.cc'], 'flushfix-unit':['flushfix_unit.cc'],
 'netcmd-config-unit':['netcmd_config_unit.cc'],
 'ktls-keyupdate':['ktls_keyupdate.cc'], 'ktls-keyupdate-unit':['ktls_keyupdate_unit.cc'],
}
# Resolve directly declared Makefile unit sources too. Alias-only and generated
# entry points above remain explicit so their interpretation can be reviewed.
for target_line,sources in re.findall(r'^([^#\n]+):([^\n]*)', (ROOT/'Makefile').read_text(),re.M):
 targets=re.findall(r'(?:build|\$\(BUILD_ROOT\))/([A-Za-z0-9_-]+)(?![\w./])',target_line)
 source_names=re.findall(r'tests/([A-Za-z0-9_]+\.(?:cc|inc))',sources)
 source_names += [stem+'.cc' for stem in re.findall(r'tests/([A-Za-z0-9_]+)\.o\b',sources) if stem+'.cc' in catalog]
 for target in targets:
  if source_names:units.setdefault(target,[]).extend(source_names)
for name,body in blocks.items():
 for target,sources in units.items():
  if target in body: jobfiles[name].update(closure(sources))
jobfiles['job_production_units'].update({'blockfix_cost.cc'})
jobfiles['job_blockfix_registry'].update({'blockfix_cost.cc'})
jobfiles['job_flip_unit'].update({'ctlfix.mk','ctlfix_unit.cc'})
jobfiles['job_differ'] = closure({'differ.py','_differ_ccfix.py'})
jobfiles['job_differ'].add('mode_equivalence.py')
for battery in ('dispatch_arity','dispatch_errors','dispatch_children','acl_subcommands','router_uniform'):
 jobfiles['job_'+battery].update(closure({battery+'.py'}))
for job in ('job_serverfix_slowlog','job_serverfix_acllog'):
 jobfiles[job].add('serverfix_alloc.cc')
for name in jobfiles:
 if name.startswith('job_iofix_'):jobfiles[name].update(closure({name.removeprefix('job_')+'.py','_iofix.py'}))
jobfiles['job_compat3'].update(closure({p.name for p in tests.glob('compat3_*.py')}))
for suffix in ('notouch','encoding','subkeys','watch','idle'):
 jobfiles['job_datafix2_'+suffix].update(closure({'datafix2_'+suffix+'.py'}))
for suffix in ('registry','mkstream','structure'):
 jobfiles['job_blockfix_'+suffix].update(closure({'compat3_blockfix.py'}))
for suffix in ('lastsave','shutdown','commands','errors'):
 jobfiles['job_persistfix2_'+suffix].update(closure({'persistfix2.py'}))
jobfiles['job_atomfix5_watch'].update(closure({'atomfix5.py'}))
jobfiles['job_atomfix5_accounting'].update(closure({'atomfix5_accounting.py'}))
for _ in range(len(blocks)):
 changed=False
 for name,body in blocks.items():
  old=len(jobfiles[name])
  for helper in blocks:
   if helper!=name and re.search(r'(?<![\w])'+re.escape(helper)+r'(?![\w])',body):
    jobfiles[name].update(jobfiles[helper])
  changed |= old!=len(jobfiles[name])
 if not changed:break
jobfiles={n:fs for n,fs in jobfiles.items() if n.startswith('job_') or n in ('feature_split_job','feature_armed_job')}
touched=subprocess.check_output(['git','diff','--name-only','05a5e01a9','HEAD','--','tests'],text=True).splitlines()
rows=[]
for f in touched:
 name=Path(f).name;jobs=[j for j,fs in jobfiles.items() if name in fs]
 if name.startswith('iofix_') or name=='_iofix.py':jobs +=[j for j in jobfiles if j.startswith('job_iofix_')]
 if name.startswith('netfix_') or name=='_netfix.py':jobs +=[j for j in blocks if j.startswith('job_netfix_')]
 if name.startswith('compat3_'):jobs+=['job_compat3','compat3_case']
 if name in ['differ.py','_differ_ccfix.py']:jobs+=['job_differ']
 if name=='txnorder_checks.inc':jobs+=['job_atomic_units','job_txnorder2']
 if name in ['txnorder_watch_unit.cc','txnorder_episodes.cc','txnorder_wake_unit.cc']:jobs+=['job_txnorder2','job_txnorder_wake']
 if name.startswith('wb_rule_'):jobs+=['job_wb_rule_units']
 if name in ['core_concurrency_unit.cc','slowlog_completion_checks.inc','wave5_dispatch_checks.inc']:jobs+=['job_core_units','job_flipfix_units']
 if name=='fixtures/nullrefresh-ledger-labels.json' or name=='nullrefresh-ledger-labels.json':jobs+=['job_abba_selftest']
 note=''
 if 'fixtures/dispatchfix-pre/' in f:
  jobs+=['job_router_uniform'];note='EX4.17 old-file recovery input; both modes and engines.'
 if name=='execfix_unit.cc':note='Historical standalone unit with no Makefile target or gate job; current EXEC/WATCH units and all execfair legs run.'
 if 'txnfix_audit/' in f:note='Historical standalone lane audit; no tests/gate.sh job. Superseding EXEC/WATCH gate rows run.'
 if name=='watchlive_gate.sh':note='Standalone WATCH stress gate; no tests/gate.sh job. Directed WATCH/EXEC and differential rows run.'
 if name=='infofields_test.py':note='Standalone serverless differential self-test; run separately.'
 if name=='gate.sh':note='Scheduler/collector interface: all correctness consumer jobs selected; measurement jobs reserved to maintainer.'
 rows.append(dict(file=f,jobs=sorted(set(jobs)),standalone_audit='txnfix_audit/' in f,note=note))
# Search actual literal strings introduced or removed in implementation. Keeping
# full tokens with test matches makes reply/error/INFO sweep reviewable.
diff=subprocess.check_output(['git','diff','--unified=0','05a5e01a9','HEAD','--','src'],text=True)
tokens=set()
for line in diff.splitlines():
 if line[:1] not in '+-' or line.startswith(('+++','---')):continue
 if '#include' in line:continue
 for token in re.findall(r'"([^"\n]{4,})"',line):
  token=token.replace('\\r\\n','').replace('\\n','')
  if re.search(r'\.(?:h|inc|cc|py)$',token):continue
  if len(token)>180 or not re.search(r'ERR|OOM|CROSSSLOT|[a-z]_[a-z]|[A-Z]{3,}|not |must |invalid|wrong|argument',token):continue
  tokens.add(token)
sweep=[]
for token in sorted(tokens):
 hits=[str(p.relative_to(ROOT)) for p in tests.rglob('*') if p.is_file() and p.suffix in ['.py','.cc','.inc','.sh'] and token in p.read_text(errors='replace')]
 if hits:
  matching=sorted({j for f in hits for j,fs in jobfiles.items() if Path(f).name in fs})
  standalone=[f for f in hits if not any(Path(f).name in fs for fs in jobfiles.values())]
  sweep.append(dict(token=token,tests=hits,jobs=matching,
                    not_resolved_by_static_scan=standalone))
out=ROOT/'docs/wave7/coverage.json';out.write_text(json.dumps(dict(touched=rows,protocol_sweep=sweep),indent=2)+'\n');print('touched',len(rows),'protocol tokens',len(sweep))
