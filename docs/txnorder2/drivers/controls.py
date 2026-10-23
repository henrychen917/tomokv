#!/usr/bin/env python3
"""Compile owner-turn controls from the exact pre-amendment merge (73e35f754).

The PRE episode fixture adds timestamp observation to previously unranked
marks. It changes neither where marks are placed nor the unconditional wait.
The separate rank-only arm changes precisely that wait predicate. Runtime PRE
and ordinary cost controls continue to use uninstrumented origin/cpp bytes.
"""
from pathlib import Path
import json
import shutil
import subprocess
import hashlib

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'build/txnorder2/episode-pre-source'
OUT=ROOT/'docs/txnorder2/controls';OUT.mkdir(parents=True,exist_ok=True)
latest=(ROOT/'src/cmd/multi.inc').read_text()
def function(name, following):return latest[latest.index(name):latest.index(following,latest.index(name))]
observer=function('uint64_t Shard::watch_writer_stamp','bool Shard::watch_writer_mark')
forget=function('void Shard::watch_writer_forget','// Invariant I,')
checker=function('void Shard::watch_writer_check','// Retires every reservation')
commands=json.loads((ROOT/'docs/txnorder2/episodes-build-command.json').read_text())
rows=[]
for arm in ['pre','rank-only']:
    source=ROOT/'build/txnorder2'/('control-'+arm);source.mkdir(parents=True,exist_ok=True)
    shutil.copytree(BASE/'src',source/'src',dirs_exist_ok=True)
    shutil.copytree(BASE/'tests',source/'tests',dirs_exist_ok=True)
    for file in ['txnorder_episodes.cc','txnorder_watch_unit.cc','atomic_survivors_unit.cc','txnorder_checks.inc']:
        shutil.copy2(ROOT/'tests'/file,source/'tests'/file)
    h=source/'src/core/shard.h';text=h.read_text()
    text=text.replace('bool watch_writer_mark(Slice key, const void* token, bool whole = false);',
                      'bool watch_writer_mark(Slice key, const void* token, bool whole = false, uint64_t stamp = 0);\n'
                      '    uint64_t watch_writer_stamp(Slice key, const void* token, bool whole = false) const;\n'
                      '    void watch_writer_forget(const void* token);\n'
                      '    void watch_writer_check(Slice key, bool whole, uint64_t stamp);')
    h.write_text(text)
    m=source/'src/cmd/multi.inc';before=m.read_text();text=before
    text=text.replace('bool Shard::watch_writer_mark(Slice key, const void* token, bool whole)',
                      'bool Shard::watch_writer_mark(Slice key, const void* token, bool whole, uint64_t stamp)')
    text=text.replace('    mark.entry_kind = 2;','    mark.entry_kind = 2;\n    mark.writer_generation = stamp ? stamp : now_ns();',1)
    at=text.index('bool Shard::watch_writer_mark');text=text[:at]+observer+forget+checker+text[at:]
    if arm=='rank-only':
        text=text.replace('if (holder.entry_kind == 2) { ready = false; continue; }',
                          'if (holder.entry_kind == 2) { if (own.age_ns > holder.writer_generation) ready = false; continue; }',1)
    m.write_text(text)
    import difflib
    (OUT/(arm+'-instrumentation.patch')).write_text(''.join(difflib.unified_diff(before.splitlines(True),text.splitlines(True),fromfile='73e35f754/multi.inc',tofile=arm+'/multi.inc')))
    for fixture in ['episodes','watch'] if arm=='pre' else ['episodes']:
        binary=source/('txnorder-'+('episodes' if fixture=='episodes' else 'watch-unit'))
        cmd=[]
        for x in commands:
            if x=='tests/txnorder_episodes.cc':x=str(source/'tests'/('txnorder_episodes.cc' if fixture=='episodes' else 'txnorder_watch_unit.cc'))
            elif x=='build/txnorder2/episodes':x=str(binary)
            elif x=='-I.':x='-I'+str(source)
            elif x.startswith('build/src/') and x.endswith('.o'):x=str(BASE/x)
            cmd.append(x)
        if fixture=='episodes':cmd+=['-DTXN_EPISODE_PRE' if arm=='pre' else '-DTXN_EPISODE_RANK_ONLY']
        with (OUT/(arm+'-'+fixture+'-build.log')).open('w') as log:
            rc=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT).returncode
        row={'arm':arm,'fixture':fixture,'command':cmd,'compile_exit':rc}
        if rc==0:
            row['sha256']=hashlib.sha256(binary.read_bytes()).hexdigest();row['runs']=[]
            cases=[(f'R{i}',) for i in range(1,13)] if fixture=='episodes' else [(c,m) for c in ['serve','readonly','handshake','rename'] for m in ['1s','2s'] if c!='rename' or m=='2s']
            for args in cases:
                log=OUT/(arm+'-'+fixture+'-'+'-'.join(args)+'.log')
                with log.open('w') as f:
                    result=subprocess.run(['taskset','-c','72-79',str(binary),*args],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=120)
                row['runs'].append({'args':args,'exit_code':result.returncode,'log':str(log.relative_to(ROOT))})
        rows.append(row);(OUT/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(arm,fixture,rc,flush=True)
