#!/usr/bin/env python3
"""Serialize final-arm correctness work on the lane's eight CPUs; never measure rates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from exec1s_pad import build as pad_build

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT/'docs/eoffix'
FINAL = ROOT/'build/eoffix/post-final/tomokv'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command, tag, env=None, required=False):
    receipt = DOC/(tag+'-driver.json')
    assert not receipt.exists(), receipt
    started = time.monotonic()
    with (DOC/(tag+'-driver.log')).open('w') as log:
        code = subprocess.run(command, cwd=ROOT, env=dict(os.environ, LC_ALL='C', **(env or {})),
                              stdout=log, stderr=subprocess.STDOUT).returncode
    receipt.write_text(json.dumps(dict(command=command, exit_code=code,
        seconds=time.monotonic()-started, env=env or {}), indent=2)+'\n')
    print(tag, 'exit', code, flush=True)
    if required and code:
        raise SystemExit(code)


def gate(tag, jobs, engine='epoll', env=None, repeat=1, capture=False, binary=FINAL):
    command = ['python3', 'tools/eoffix.py', '--tag', tag, '--jobs', jobs,
               '--binary', str(binary), '--engine', engine, '--port', '21900', '--keep-going']
    if repeat > 1: command += ['--repeat', str(repeat), '--archive-data']
    if capture: command += ['--capture']
    run(command, tag, env)


def maintenance():
    for name in ['archive_data', 'dedup']:
        subprocess.run(['python3', f'tools/eoffix_{name}.py'], check=True)


def artifacts():
    assert len(json.loads((DOC/'final-build.json').read_text())) == 4
    FINAL.parent.mkdir(exist_ok=True)
    assert not FINAL.exists()
    shutil.copy2(ROOT/'build/tomokv', FINAL)
    for fixture in ['aof','eof']:
        run(['python3', 'tools/eoffix_aof.py', 'post', '--tag', 'final-'+fixture+'-native',
             '--fixture', fixture], 'final-'+fixture+'-build', required=True)
    for kind in ['ordinary', 'parser', 'receive']:
        command = ['python3', 'tools/eoffix_receive_counts.py', 'post', '--tag', 'release']
        if kind != 'receive':
            command = ['python3', 'tools/eoffix_counts.py', 'post', '--kind', kind, '--tag', 'release']
            if kind == 'parser':
                command += ['--only', 'PARSE-GET,PARSE-SET,PARSE-INCR,PARSE-MGET,PARSE-MSET']
        run(command, 'final-census-'+kind, required=True)
    run(['python3', 'tools/eoffix_bind.py', '--arm', 'post', '--tag', 'release'],
        'final-binding', required=True)
    subprocess.run(['python3','tools/eoffix_retire_scopes.py','--arm','post','--tag','release'],check=True)
    output = ROOT/'build/eoffix/layout-final'
    output.mkdir(exist_ok=True)
    pad_build(ROOT/'build/eoffix/pre-source', ROOT, output, DOC/'pad-a-final.json')
    rows = []
    for arm, path in [('PRE',ROOT/'build/eoffix/pre-rebuilt'),('POST',FINAL),
                      ('POST-layout',output/'POST-layout'),('PAD-A',output/'PAD-A')]:
        sections = subprocess.check_output(['size','-A',str(path)],text=True).splitlines()
        rows.append(dict(arm=arm,path=str(path.relative_to(ROOT)),sha256=sha(path),
                         bytes=path.stat().st_size,
                         text_bytes=int(next(x.split()[1] for x in sections if x.startswith('.text ')))))
    (DOC/'arms-final.json').write_text(json.dumps(rows,indent=2)+'\n')
    assert sha(FINAL) == sha(ROOT/'build/tomokv')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['artifacts','cold','tcl','differ','regressions','txn','harness'])
    a=p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(8))
    os.environ.update(LC_ALL='C', CXX='g++ -gz=zlib', CC='cc -gz=zlib')
    if a.phase=='artifacts': artifacts(); return
    assert sha(FINAL)==sha(ROOT/'build/tomokv')
    if a.phase=='cold':
        gate('final-eof-aof', 'wave14_epoll_eof eoffix_aof wave14_eof_data netio-1s netio-2s',
             env=dict(WAVE14_EOF_DIRECTORY=str(ROOT/'build/eoffix/final-eof-native'),
                      EOFFIX_AOF_DIRECTORY=str(ROOT/'build/eoffix/final-aof-native-v2')))
        gate('final-layout', 'netio-1s netio-2s wave14_eof_data',
             binary=ROOT/'build/eoffix/layout-final/POST-layout')
        gate('final-pad', 'netio-1s netio-2s', binary=ROOT/'build/eoffix/layout-final/PAD-A')
    elif a.phase=='tcl':
        for engine in ['epoll','uring']:
            for index in range(1,4):
                gate(f'final-tcl-{engine}-{index}', 'redis_tcl', engine)
                maintenance()
    elif a.phase=='differ':
        for engine in ['epoll','uring']:
            gate('final-differ-'+engine, 'differ-split differ-armed', engine)
            maintenance()
    elif a.phase=='txn':
        for engine in ['epoll','uring']:
            gate('txn-final-'+engine, 'txnorder-fused-0', engine, repeat=50, capture=True)
            maintenance()
    elif a.phase=='harness':
        run(['python3','tests/gates_test.py'],'gates-test-release-complete',required=True)
        previous=json.loads((DOC/'build-freshness-final.json').read_text())
        for index, row in enumerate(previous['commands']):
            run(row['command'],f'freshness-release-{index}',required=True)
    elif a.phase=='regressions':
        # Jobs with an internal all-mode/all-engine matrix run once.
        internal = 'netcmd_units wb_rule_units wbland_units blockfix2 blockfix_registry blockfix_structure blockfix_mkstream txnorder_fifo txnorder_fifo_live txnorder_chain txnorder_index txnorder_wound txnorder2 txnorder_wake persistfix_units tls netfix_tls slotless wb_mixed inline_quoted ntfix_input crlffix clientcompat-enable-race iofix-deferred iofix-hz iofix-sleep iofix-signal netfix_query_stats netfix_unix netfix_config netfix_idle_buffers netcap clientcompat-pause clientcompat-disconnect clientcompat-multi-tracking clientcompat-multi-controls persistfix2_shutdown persistfix2_lastsave persistfix2_commands persistfix2_errors persistfmt persistfmt_aof_error snapfix_shutdown notify_aof serverfix_waitaof'
        gate('final-internal', internal, binary=ROOT/'build/tomokv')
        maintenance()
        for engine in ['epoll','uring']:
            live = 'feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 blockfix4 aoforder respcompat clientfix climonfix txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 fused-0 fused-1 txn_group_fused txn_group_split wb_policy'
            live += ' '+ ' '.join(f'respresume-{case}-{mode}-{engine}' for case in ['fragment','cpu','neighbour'] for mode in ['1s','2s'])
            live += ' '+ ' '.join(f'{job}-{mode}-{engine}' for job in ['multifix','climonfix4'] for mode in ['1s','2s'])
            gate('final-live-'+engine,live,engine,dict(GATE_SHUTDOWN_NET_IO=engine))
            maintenance()
            for fused in ['0','1']:
                # atomic_floor's existing partial NO_RATES switch retains pipeorder
                # and explicitly records its throughput row as NOT RUN.
                jobs=f'release_batteries atomic_floor replyoff aof_frame aof-{engine} snapshot-{engine}'
                gate(f'final-mode-{engine}-{fused}',jobs,engine,dict(GATE_TXN_FUSED=fused))
                maintenance()
    assert sha(FINAL)==sha(ROOT/'build/tomokv')


if __name__=='__main__': main()
