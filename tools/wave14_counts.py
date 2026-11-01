#!/usr/bin/env python3
"""Finite production instruction scopes, including outlined STL and Lua VM code.

Fixture glue and shared libraries are excluded. No server, load, timing or rates.
"""
import argparse
import bisect
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import subprocess
import wave13_counts as census
from wave14 import ROOT, BUILD, DOC, PRE, save, sha

census.BUILD = BUILD/'counts'
census.DOC = DOC/'instructions'

def trace(prepared, label, ns, case):
    command, mode, batch, atomic, local = case
    ranges, argv, digest = prepared
    target = census.DOC/label/('-'.join(map(str,(ns,*case)))+'.json')
    if target.exists():
        old = json.loads(target.read_text())
        if old['probe_sha256'] == digest and old['tracer_sha256'] == sha(census.BUILD/'trace') and \
                Path(str(target)+'.sites.gz').exists():
            return old
    target.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(argv+list(map(str,case)), text=True, capture_output=True, timeout=900)
    if run.returncode:
        target.with_suffix('.failed.log').write_text(run.stderr+run.stdout[-5000:])
        raise RuntimeError(str(target)+' '+run.stderr+run.stdout[-1500:])
    record = json.loads(next(line[6:] for line in run.stdout.splitlines() if line.startswith('TRACE=')))
    starts = [r[0] for r in ranges]; functions = {}
    for pc, count in record['sites'].items():
        at = int(pc,16); i = bisect.bisect_right(starts,at)-1
        assert i >= 0 and at < ranges[i][1]
        name = ranges[i][3]; functions[name] = functions.get(name,0)+count
    row = dict(arm=label, namespace=ns, command=command, mode=mode, batch=batch,
        atomic=atomic, local=local, probe_sha256=digest, tracer_sha256=sha(census.BUILD/'trace'),
        total=sum(functions.values()), functions=functions,
        clock_calls=record['clock_calls'], excluded_calls=record['excluded_calls'])
    save(target,row)
    with gzip.GzipFile(filename=str(target)+'.sites.gz',mode='wb',mtime=0) as f:
        f.write(json.dumps(record).encode())
    target.with_suffix('.log').write_text(' '.join(argv+list(map(str,case)))+'\n'+run.stderr+
        '\n'.join(line for line in run.stdout.splitlines() if not line.startswith('TRACE=')))
    print(label, ns, *case, row['total'], flush=True)
    return row

def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser()
    p.add_argument('arm',choices=('pre','post'))
    p.add_argument('--kind',choices=('ordinary','scripts','session','other','parser'),required=True)
    p.add_argument('--only',default='')
    p.add_argument('--tag',default='')
    p.add_argument('--no-build',action='store_true')
    p.add_argument('--build-only',action='store_true')
    a = p.parse_args()
    source = PRE if a.arm == 'pre' else ROOT
    objects = source/'build'
    label = a.arm+'-'+a.kind+('-'+a.tag if a.tag else '')
    fixtures = dict(ordinary='tests/blockfix4_scope.cc', scripts='tests/wave12_scope.cc',
        session='tests/clientcompat_session_scope.cc', other='tests/wave12_scope.cc',
        parser='tests/wave14_parser_scope.cc')
    verbs = dict(ordinary=['GET','SET','INCR','MGET','MSET','LPUSH','RPUSH'],
        scripts=['EVAL-single','EVAL-cross','EVALSHA-single','EVALSHA-cross'],
        session=['EXEC-single','EXEC-cross'], other=['READLOCAL-GET','FLUSHALL-empty','FLUSHALL-small'],
        parser=['PARSE-GET','PARSE-SET','PARSE-INCR'])
    commands = a.only.split(',') if a.only else verbs[a.kind]
    census.BUILD.mkdir(parents=True,exist_ok=True)
    tracer = census.BUILD/'trace'
    if not tracer.exists():
        subprocess.run(['g++','-std=c++20','-O2','-g','tools/scriptfix3_trace.cc','-o',str(tracer)],check=True)
    rows = []
    for ns in ('normal','db0'):
        binary = (census.BUILD/'scopes'/(label+'-'+ns)/'probe' if a.no_build else
                  census.build(label,source,objects,ns,fixtures[a.kind]))
        if a.build_only: continue
        prepared = census.prepare(binary,objects,ns,'lua')
        cases = [(c,mode,batch,atomic,local) for c in commands
            for mode in (('1s',) if c=='READLOCAL-GET' else ('1s','2s'))
            for batch in ((1,32) if a.kind in ('ordinary','parser') or c=='READLOCAL-GET' else (1,))
            for atomic in ((1,) if c=='READLOCAL-GET' or a.kind=='parser' else (0,1))
            for local in ((0,1) if a.kind=='parser' and mode=='1s' else (-1,))]
        with ThreadPoolExecutor(max_workers=16) as pool:
            rows += list(pool.map(lambda case:trace(prepared,label,ns,case),cases))
    if not a.build_only:
        save(census.DOC/label/'counts.json',dict(server_sha256=sha(objects/'tomokv'),
            fixture_sha256=sha(ROOT/fixtures[a.kind]), rows=rows))

if __name__ == '__main__': main()
