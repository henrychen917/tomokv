#!/usr/bin/env python3
"""PRE identity audit including INCR and MGET/MSET's shared dispatch bodies."""
import json,re,subprocess
from pathlib import Path
from lbstall_artifacts import Elf
ROOT=Path(__file__).resolve().parents[1]
PRE=ROOT/'build/execindex/pre-source/build';POST=ROOT/'build';OUT=ROOT/'docs/execindex'
rows=[]
for ns in ['src','db0/src']:
    for obj in ['t_string.o','t_string_notify.o','xshard.o']:
        rel=ns+'/cmd/'+obj;a=Elf(PRE/rel);b=Elf(POST/rel);old,new=a.functions(),b.functions();names=list(old)
        labels=subprocess.check_output(['c++filt'],input='\n'.join(names),text=True).splitlines()
        for sym,name in zip(names,labels):
            if not re.search(r'cmd_(get|set|incr)(?:[<(])|cmd_xshard_only|xshard_(prepare|execute)\(',name):continue
            n=new.get(sym)
            rows.append(dict(object=rel,symbol=sym,name=name,pre_size=old[sym]['size'],post_size=n['size'] if n else 0,
                raw_equal=bool(n) and a.body(old[sym])==b.body(n),canonical_equal=bool(n) and a.canonical(old[sym])==b.canonical(n)))
assert sum('cmd_incr' in r['name'] for r in rows)==4
(OUT/'command-bodies.json').write_text(json.dumps(rows,indent=2)+'\n')
allrows=json.loads((OUT/'hot-final.json').read_text())
keys={(r['object'],r['symbol']) for r in allrows}
allrows += [dict(r,relocation_equal=r['canonical_equal']) for r in rows if (r['object'],r['symbol']) not in keys]
changed=[]
for r in allrows:
    if r['relocation_equal']:continue
    name=r['name']
    if 'FlatStore::' in name:
        reason='Compiler inlining/register allocation spillover from the changed translation unit; store source is unchanged. This is not claimed byte-identical.'
    elif 'xshard_execute' in name:
        reason='Shared scatter body includes the changed transaction readiness/finalization helpers; indexed cold branches and compiler allocation differ. Bounded MGET/MSET instruction scopes are checked separately.'
    elif 'execute_multi_unit' in name or '::{lambda(void*, tomo' in name:
        reason='Retry promotion callback now accepts a stable MultiOwnerRetryNode handle instead of a Task; old callback symbols are replaced.'
    elif any(x in name for x in ['execute<','execute_timed<','parse_and_dispatch','sweep','fused_pass','drain_tasks','run_loop']):
        reason='Owner retry service/dispatch uses the intrusive queues; inlined retry branches and compiler decisions change this enclosing body. Ordinary command scopes and the maintainer null cover its main-command path.'
    else:
        reason='Compiler spillover in an enclosing owner/IO helper after intrusive retry replacement; unchanged source outside the retry implementation, explicitly retained for the maintainer null.'
    changed.append(dict(r,reason=reason))
(OUT/'changed-bodies.json').write_text(json.dumps(changed,indent=2)+'\n')
print('selected',len(allrows),'changed',len(changed),'direct command differences',sum(not r['canonical_equal'] for r in rows if 'cmd_' in r['name']))
for r in rows:
    if not r['canonical_equal']:print('DIFF',r['object'],r['name'])
