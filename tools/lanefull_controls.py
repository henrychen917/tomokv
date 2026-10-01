#!/usr/bin/env python3
"""Build/run serverless LaneFull controls; all throwaway edits stay under build/.

A detected mutant must exit 1 at its named assertion, never merely crash/timeout.
No server binary is run. Invoke this script under taskset -c 112-127.
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/cleanup-lanefull/controls'
FLAGS=['g++','-std=c++20','-O0','-g','-pthread','-DTOMO_JEMALLOC',
       '-DTOMO_CORE_CONCURRENCY_TEST','-DTOMO_LANEFULL_ONLY']
IO='src/core/io_loop.h';EX='src/core/ex_loop.h';THREAD='src/core/thread.h';INFO='src/cmd/t_server.cc'
MUTANTS={
 'capacity-demote':(IO,'fused_executor_->note_local_read_lane_full();\n                                    break;',
  'fused_executor_->note_local_read_lane_full();\n                                    read_local_eligible = false;\n                                    read_local_fallback_reason = ReadLocalFallbackReason::ContextRoute;',
  'lanefull','eligible pressure read published an owner task'),
 'bypass-cap':(EX,'const uint32_t cap = srv_->debug_read_local_lane_cap();','const uint32_t cap = 0;',
  'lanefull','capped pressure must exceed uncapped pressure'),
 'omit-restore':(EX,'const uint16_t want = cap == 0 ? static_cast<uint16_t>(kInboxSlots)',
  'const uint16_t want = cap == 0 ? read_local_impl().lane_admit_cap',
  'lanefull','cap reset must restore derived-lane admission'),
 'consume-deferred-frame':(IO,'fused_executor_->note_local_read_lane_full();\n                                    break;',
  'fused_executor_->note_local_read_lane_full();\n                                    conn.advance_parse(consumed); break;',
  'lanefull','ordered reply has exact value'),
 'drop-local-marker':(EX,'                    self_->note_command(op.spec->id);',
  '                    self_->note_command(op.spec->id); op.route_flags_ &= ~(1u << 6);',
  'lanefull','every deferred read completes locally'),
 'omit-quota':(IO,'rob.pending_read_local_count() >= read_local_quota','false',
  'lanefull','fair-share quota window did not open'),
 'omit-local-hit':(EX,'stats.hits += completed;','/* omitted local hit accounting */',
  'lanefull','exact local completions with no fallback'),
 'omit-mget-hit':(EX,'stats.mget_local_hits += prefix_mget_hits;','/* omitted MGET accounting */',
  'lanefull','exact local MGET completions'),
 'omit-done':(EX,'                    op.state.store(OpState::Done, std::memory_order_release);',
  '                    /* omitted Done publication */','lanefull','bounded reparse liveness failed'),
 'wrong-reply':(EX,'reply_bulk(op.sink(), object->read_local_str_value(stable_flags));','reply_bulk(op.sink(), Slice("wrong"));',
  'lanefull','ordered reply has exact value'),
 'omit-reset-baseline':(INFO,'        read_local.defer_quota = minus_baseline(\n            read_local.defer_quota, baseline.read_local.defer_quota);',
  '        /* omitted surviving quota baseline */','lanefull-info','surviving aggregate/baseline mismatch'),
 'omit-aggregate':(INFO,'    total.defer_lane_full += local.defer_lane_full;','    /* omitted surviving aggregation */',
  'lanefull-info','surviving aggregate/baseline mismatch'),
 'omit-total':(THREAD,'               fallback_generation;','               0;',
  'lanefull-info','surviving aggregate/baseline mismatch'),
 'remove-first-reserved':(THREAD,'    std::byte reserved_lane_full[8]{};','',None,'static assertion failed'),
 'remove-second-reserved':(THREAD,'    std::byte reserved_mget_lane_full[8]{};','',None,'static assertion failed'),
}


def libraries(arm,db0=False,override=None):
    commands=[shlex.split(x) for x in (arm/'build.log').read_text().splitlines() if x.startswith('g++ ')]
    links=[c for c in commands if 'build/tomokv' in c]
    if not links:
        commands=[shlex.split(x) for x in (ROOT/'build/cleanup-lanefull/PRE/build.log').read_text().splitlines() if x.startswith('g++ ')]
        links=[c for c in commands if 'build/tomokv' in c]
    link=links[-1]
    paths=[x for x in link if x.endswith('.o') and not x.endswith('/main.o')
           and (db0 or not x.startswith('build/db0/'))]
    return [str(override) if override and x=='build/src/cmd/t_server.o' else
            str(arm/x.removeprefix('build/')) for x in paths]


def link(obj,out,arm,db0=False,override=None):
    cmd=['g++','-pthread',str(obj),*libraries(arm,db0,override),'-o',str(out),
         '-ljemalloc','-luring','-pthread','-lssl','-lcrypto','-lm']
    subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)


def positive(arm,db0=False):
    tag='positive-db0' if db0 else 'positive';d=OUT/tag;d.mkdir(parents=True,exist_ok=True)
    cmd=FLAGS+(['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0'] if db0 else [])+[
        '-I.', '-c','tests/core_concurrency_unit.cc','-o',str(d/'fixture.o')]
    with (d/'build.log').open('w') as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    link(d/'fixture.o',d/'unit',arm,db0)
    p=subprocess.run([str(d/'unit'),'lanefull'],capture_output=True,text=True,timeout=60)
    (d/'run.log').write_text(p.stdout+p.stderr)
    assert p.returncode==0,(tag,p.stdout,p.stderr)
    return dict(name=tag,returncode=p.returncode,log=str(d/'run.log'))


def mutant(name,arm):
    file,old,new,case,expected=MUTANTS[name];d=OUT/name;d.mkdir(parents=True,exist_ok=True)
    src=d/'source';shutil.copytree(ROOT/'src',src/'src',dirs_exist_ok=True)
    text=(src/file).read_text();assert text.count(old)==1,(name,text.count(old))
    (src/file).write_text(text.replace(old,new))
    with (d/'build.log').open('w') as log:
        if file==INFO or name=='omit-total':
            cmd=['g++','-std=c++20','-O2','-g','-Wall','-Wextra','-march=native','-pthread',
                 '-DTOMO_JEMALLOC','-I.', '-c',INFO,'-o',str(d/'t_server.o')]
            p=subprocess.run(cmd,cwd=src,stdout=log,stderr=subprocess.STDOUT)
            assert p.returncode==0,name
            obj=OUT/'positive/fixture.o';override=d/'t_server.o'
        else:
            cmd=FLAGS+['-I'+str(src),'-I.', '-c','tests/core_concurrency_unit.cc','-o',str(d/'fixture.o')]
            p=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            if case is None:
                assert p.returncode!=0 and expected in (d/'build.log').read_text(),name
                return dict(name=name,compile_rejected=True,expected=expected)
            assert p.returncode==0,name
            obj=d/'fixture.o';override=None
        link(obj,d/'unit',arm,override=override)
    p=subprocess.run([str(d/'unit'),case],capture_output=True,text=True,timeout=60)
    (d/'run.log').write_text(p.stdout+p.stderr)
    assert p.returncode==1 and expected in p.stderr,(name,p.returncode,p.stdout,p.stderr)
    return dict(name=name,returncode=p.returncode,expected=expected,log=str(d/'run.log'))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--arm',type=Path,default=ROOT/'build/cleanup-lanefull/POST')
    ap.add_argument('--only',nargs='*');ap.add_argument('--positive',action='store_true');a=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);results=[]
    if a.positive or not a.only:
        for db0 in [False,True]:results.append(positive(a.arm,db0));print(results[-1],flush=True)
    names=a.only if a.only else list(MUTANTS)
    if a.positive:names=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for r in pool.map(lambda n:mutant(n,a.arm),names):results.append(r);print(r,flush=True); (OUT/'progress.json').write_text(json.dumps(results,indent=2)+'\n')
    (OUT/('results-'+('-'.join(a.only) if a.only else 'positive' if a.positive else 'all')+'.json')).write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':main()
