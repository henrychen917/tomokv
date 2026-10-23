#!/usr/bin/env python3
"""Compile-only immutable dispatch-field trial; never changes production objects."""
import concurrent.futures,json,os,re,shlex,shutil,subprocess
from pathlib import Path
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64,96)))
ROOT=Path(__file__).resolve().parents[2];VARIANT=os.getenv('WAVE5_FAST_VARIANT','fields');OUT=ROOT/('build/wave5/fast-trial' if VARIANT=='fields' else 'build/wave5/fast-trial-'+VARIANT);OUT.mkdir(exist_ok=True)
SRC=OUT/'source'
if not SRC.exists():
 SRC.mkdir()
 for d in ('src','third_party'):shutil.copytree(ROOT/d,SRC/d,copy_function=os.link)
p=SRC/'src/core/ex_execute.inc';s=(ROOT/'src/core/ex_execute.inc').read_text()
s=s.replace('op.spec->','spec->').replace('spec->flags','flags').replace('t.scatter','scatter')
s=s.replace('        Op& op = t.client->rob().at(t.op_id);','''        Op& op = t.client->rob().at(t.op_id);
        // Dispatch publishes these fields before Issued; owners do not replace
        // the descriptor, and retirement cannot recycle it before Done.
        const CommandSpec* const spec = op.spec;
        const uint32_t flags = spec->flags;
        const bool scatter = t.scatter != nullptr;''')
if VARIANT in ('client','context'):
 a=s.index('        Op& op = t.client->rob().at(t.op_id);')
 s=s[:a]+'        Client* const client = t.client;\n'+s[a:].replace('t.client','client')
 if VARIANT=='context':
  a=s.index('        Op& op = client->rob().at(t.op_id);')
  s=s[:a]+'        ThreadCtx* const thread = self_;\n        Server* const server = srv_;\n'+s[a:].replace('self_','thread').replace('srv_','server')
if VARIANT in ('writes','defer','spec','scatter'):
 if VARIANT=='spec':
  s=s.replace('        const uint32_t flags = spec->flags;\n','');s=re.sub(r'\bflags\b', 'spec->flags',s).replace('!scatter', '!t.scatter').replace('if (scatter)', 'if (t.scatter)').replace('        const bool scatter = t.scatter != nullptr;\n','')
 elif VARIANT=='scatter':
  s=s.replace('        const uint32_t flags = spec->flags;\n','').replace('        const CommandSpec* const spec = op.spec;\n','').replace('spec->','op.spec->');s=re.sub(r'\bflags\b','op.spec->flags',s)
 else:
  s=s.replace('        const bool scatter = t.scatter != nullptr;', '        const bool scatter = t.scatter != nullptr;\n        const bool writes = flags & (CmdFlags::Write | CmdFlags::SnapshotWrite);')
  s=s.replace('(flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))','writes')
 if VARIANT=='defer':
  s=s.replace('atomic_deferred_.push_back(t);','defer_atomic_task(t);')
  h=SRC/'src/core/ex_loop.h';hs=(ROOT/'src/core/ex_loop.h').read_text()
  hs=hs.replace('    void note_lb_hash(', '    __attribute__((noinline, cold)) void defer_atomic_task(const Task& task) { atomic_deferred_.push_back(task); }\n\n    __attribute__((always_inline)) void note_lb_hash(')
  h.unlink();h.write_text(hs)
if VARIANT in ('lbguard','lbdefer','flags','late'):
 s=s.replace('if (!scatter) note_lb_hash(sh, op.hash);','if (!scatter && lb_sample_rate_) note_lb_hash(sh, op.hash);')
 if VARIANT=='flags':
  s=s.replace('spec->', 'op.spec->').replace('        const CommandSpec* const spec = op.spec;\n','')
 if VARIANT=='late':
  fields='        const CommandSpec* const spec = op.spec;\n        const uint32_t flags = spec->flags;\n        const bool scatter = t.scatter != nullptr;\n'
  s=s.replace(fields,'')
  pos=s.index('        if (!scatter &&')
  s=s[:pos]+fields+s[pos:]
 if VARIANT=='lbdefer':
  s=s.replace('atomic_deferred_.push_back(t);','defer_atomic_task(t);')
  h=SRC/'src/core/ex_loop.h';hs=(ROOT/'src/core/ex_loop.h').read_text()
  hs=hs.replace('    void note_lb_hash(', '    __attribute__((noinline, cold)) void defer_atomic_task(const Task& task) { atomic_deferred_.push_back(task); }\n\n    void note_lb_hash(')
  h.unlink();h.write_text(hs)
if VARIANT in ('spec','scatter'):s=s.replace('if (!t.scatter) note_lb_hash(sh, op.hash);','if (!t.scatter && lb_sample_rate_) note_lb_hash(sh, op.hash);').replace('if (!scatter) note_lb_hash(sh, op.hash);','if (!scatter && lb_sample_rate_) note_lb_hash(sh, op.hash);')
if VARIANT=='guard':
 s=(ROOT/'src/core/ex_execute.inc').read_text()
 s=s.replace('            xshard_task_should_defer(*srv_, sh, t, op)) {', '            ((t.scatter || op.atomic_hazard()) &&\n             xshard_task_should_defer(*srv_, sh, t, op))) {')
if p.exists():p.unlink()
p.write_text(s)
objs=['src/main.o','db0/src/main.o','src/core/genthread.o','db0/src/core/genthread.o'];mapping={}
lines=(ROOT/'build/wave5/build-function-exec.log').read_text().splitlines()
def build(obj):
 dest=OUT/(obj.replace('/','_'));cmd=shlex.split(next(s for s in lines if s.startswith('g++ ') and s.endswith(' -o build/'+obj)));cmd[cmd.index('-o')+1]=str(dest)
 with (OUT/(dest.name+'.log')).open('w') as f:rc=subprocess.run(cmd,cwd=SRC,stdout=f,stderr=subprocess.STDOUT).returncode
 assert rc==0,obj
 return 'build/'+obj,str(dest)
with concurrent.futures.ThreadPoolExecutor(4) as pool:mapping=dict(pool.map(build,objs))
(OUT/'objects.json').write_text(json.dumps(mapping,indent=2)+'\n')
