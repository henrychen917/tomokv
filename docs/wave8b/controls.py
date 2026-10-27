#!/usr/bin/env python3
"""Throwaway broken mechanisms must fail the directed serverless witness."""
import hashlib,json,os,resource,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT)
os.sched_setaffinity(0,set(range(64,80)));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
OUT=ROOT/'build/wave8b/controls';OUT.mkdir(parents=True,exist_ok=True)
DOC=ROOT/'docs/wave8b/controls';DOC.mkdir(parents=True,exist_ok=True)
recipe=subprocess.check_output(['make','-n','-f','Makefile','-f','tools/wave8b.mk','-W','tests/wave8b_latency_unit.cc','build/wave8b-latency-unit'],text=True)
cmds=[shlex.split(s) for s in recipe.splitlines() if s.startswith('g++ ')]
compile=next(c for c in cmds if '-c' in c and 'tests/wave8b_latency_unit.cc' in c)
link=next(c for c in cmds if '-c' not in c and 'build/wave8b-latency-unit' in c)
receipts=[]
for case in ('scan','stale','callback','orphan'):
 d=OUT/case;d.mkdir(exist_ok=True);binary=d/'broken';obj=d/'broken.o'
 if case=='scan':
  source=(ROOT/'src/cmd/multi.inc').read_text().replace('void multi_retire(Client& client, Op& op, std::vector<MultiExecState*>& deferred) {','void multi_retire(Client& client, Op& op, std::vector<MultiExecState*>& deferred) {\n    latency_tracking_discard_pending();')
  inc=d/'multi.inc';inc.write_text(source)
  cc=d/'xshard.cc';cc.write_text((ROOT/'src/cmd/xshard.cc').read_text().replace('#include "multi.inc"','#include "'+str(inc)+'"'))
  recipes=subprocess.check_output(['make','-Bn','build/src/cmd/xshard.o'],text=True)
  cmd=shlex.split(next(s for s in recipes.splitlines() if s.startswith('g++ ') and s.endswith(' -o build/src/cmd/xshard.o')))
  cmd[cmd.index('src/cmd/xshard.cc')]=str(cc);cmd+=['-I'+str(ROOT/'src/cmd'),'-g0']
  replacement='build/src/cmd/xshard.o'
 else:
  source=(ROOT/'src/cmd/latency_tracking.cc').read_text()
  if case=='stale': source=source.replace('    if (started <= disabled_cut_ns.load(std::memory_order_acquire)) return;\n','')
  elif case=='callback': source=source.replace('if (started > cut) record_generation(executor, op, ns, cut);','if (now_ns() - ns > cut) record_generation(executor, op, ns, cut);')
  else: source=source.replace('            else latency_tracking_forget(op);\n','')
  cc=d/'latency_tracking.cc';cc.write_text(source)
  unit=d/'unit.cc';unit.write_text((ROOT/'tests/wave8b_latency_unit.cc').read_text().replace('#include "src/cmd/latency_tracking.cc"','#include "'+str(cc)+'"'))
  cmd=compile.copy();cmd[cmd.index('tests/wave8b_latency_unit.cc')]=str(unit)
  cmd+=['-I'+str(ROOT/'src/cmd'),'-I'+str(ROOT/'tests')]
  replacement='build/wave8b-latency-unit.o'
 cmd[cmd.index('-o')+1]=str(obj)
 with (DOC/(case+'-build.log')).open('w') as log:subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT)
 ld=[str(obj) if x==replacement else x for x in link];ld[ld.index('-o')+1]=str(binary)
 with (DOC/(case+'-link.log')).open('w') as log:subprocess.run(ld,check=True,stdout=log,stderr=subprocess.STDOUT)
 result=subprocess.run([str(binary)],capture_output=True,text=True)
 (DOC/(case+'.log')).write_text(result.stdout+result.stderr)
 assert result.returncode==-6,(case,result.returncode)
 if case=='orphan': assert 'rejected parent retained 1 script-child maps' in result.stderr
 trace=subprocess.run(['gdb','-nx','-batch','-ex','run','-ex','bt',str(binary)],capture_output=True,text=True)
 (DOC/(case+'-backtrace.log')).write_text(trace.stdout+trace.stderr)
 assert 'SIGABRT' in trace.stdout
 receipts.append(dict(case=case,compile=cmd,link=ld,exit=result.returncode,sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),reason={'scan':'Unconditional retirement scan','stale':'Reintroduced stale pending slice after no/yes','callback':'Delayed callback reconstructs old beginning after no/yes','orphan':'Rejected old parent leaves post-enable script children behind'}[case]))
 print('EXPECTED RED',case,result.returncode,flush=True)
(DOC/'receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
