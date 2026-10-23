#!/usr/bin/env python3
"""Trace touched batteries and changed protocol tokens to real gate job bodies."""
import ast,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];tests=ROOT/'tests';gate=(tests/'gate.sh').read_text()
blocks={m[1]:m[2] for m in re.finditer(r'^(job_[A-Za-z0-9_]+|[A-Za-z0-9_]*_legs|compat3_case)\(\)\{\n(.*?)(?=^}\n)',gate,re.M|re.S)}
files={p.name:p for p in tests.glob('*.py')};deps={}
for name,p in files.items():
 try:t=ast.parse(p.read_text())
 except (SyntaxError,UnicodeDecodeError):continue
 deps[name]={x+'.py' for n in ast.walk(t) for x in ([n.module.split('.')[0]] if isinstance(n,ast.ImportFrom) and n.module else [a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else []) if x+'.py' in files}
def closure(names):
 out=set(names);todo=list(names)
 while todo:
  for n in deps.get(todo.pop(),set())-out:out.add(n);todo.append(n)
 return out
jobfiles={n:closure(set(re.findall(r'tests/([A-Za-z0-9_]+\.(?:py|cc|sh|inc))',b))) for n,b in blocks.items()}
touched=subprocess.check_output(['git','diff','--name-only','a7dfb9d23','HEAD','--','tests'],text=True).splitlines()
rows=[]
for f in touched:
 name=Path(f).name;jobs=[j for j,fs in jobfiles.items() if name in fs]
 if name.startswith('iofix_'):jobs+=['iofix_legs']
 if name.startswith('netfix_') or name=='_netfix.py':jobs +=[j for j in blocks if j.startswith('job_netfix_')]
 if name.startswith('compat3_'):jobs+=['job_compat3','compat3_case']
 if name in ['differ.py','_differ_ccfix.py']:jobs+=['job_differ']
 if name=='txnorder_checks.inc':jobs+=['job_atomic_units','job_txnorder2']
 if name in ['txnorder_watch_unit.cc','txnorder_episodes.cc','txnorder_wake_unit.cc']:jobs+=['job_txnorder2','job_txnorder_wake']
 if name.startswith('wb_rule_'):jobs+=['job_wb_rule_units']
 if name in ['core_concurrency_unit.cc','slowlog_completion_checks.inc']:jobs+=['job_core_units','job_flipfix_units']
 if name=='fixtures/nullrefresh-ledger-labels.json' or name=='nullrefresh-ledger-labels.json':jobs+=['job_abba_selftest']
 rows.append(dict(file=f,jobs=sorted(set(jobs)),standalone_audit='txnfix_audit/' in f))
# Search actual literal strings introduced or removed in implementation. Keeping
# full tokens with test matches makes reply/error/INFO sweep reviewable.
diff=subprocess.check_output(['git','diff','--unified=0','a7dfb9d23','HEAD','--','src'],text=True)
tokens=set()
for line in diff.splitlines():
 if line[:1] not in '+-' or line.startswith(('+++','---')):continue
 for token in re.findall(r'"([^"\n]{4,})"',line):
  token=token.replace('\\r\\n','').replace('\\n','')
  if len(token)>180 or not re.search(r'ERR|OOM|CROSSSLOT|[a-z]_[a-z]|[A-Z]{3,}|not |must |invalid|wrong|argument',token):continue
  tokens.add(token)
sweep=[]
for token in sorted(tokens):
 hits=[str(p.relative_to(ROOT)) for p in tests.rglob('*') if p.is_file() and p.suffix in ['.py','.cc','.inc','.sh'] and token in p.read_text(errors='replace')]
 if hits:
  matching=sorted({j for f in hits for j,fs in jobfiles.items() if Path(f).name in fs})
  sweep.append(dict(token=token,tests=hits,jobs=matching))
out=ROOT/'docs/wave5/coverage.json';out.write_text(json.dumps(dict(touched=rows,protocol_sweep=sweep),indent=2)+'\n');print('touched',len(rows),'protocol tokens',len(sweep))
