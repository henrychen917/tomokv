#!/usr/bin/env python3
"""Run the historical 215-row plan with explicit lane resource remapping.

Receipts preserve exit codes (including negative controls), commands and digests.
Only subprocess groups created here are stopped. AOF prepare/verify/scan share
their original directory. No performance gate or throughput probe is invoked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/txnorder2/runtime'
RUN_ID = os.environ.get('TXNORDER_RUN_ID', 'resume')
DATA = ROOT / ('build/txnorder2/runtime-data-' + RUN_ID)
PRE = ROOT / 'build/txnorder2/pre-source/build/tomokv'
POST = ROOT / 'build/txnorder2/post/tomokv'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def transform(value):
    if isinstance(value, list): return [transform(x) for x in value]
    if isinstance(value, dict): return {k: transform(v) for k,v in value.items()}
    if not isinstance(value, str): return value
    value = value.replace('57-63','85-95').replace('48-55','64-71')
    if value == '56': value = '84'
    if re.fullmatch(r'226\d\d', value): value = str(int(value) + 5200)
    value = value.replace(str(ROOT / 'build/txnorder/pre/tomokv'), str(PRE))
    value = value.replace(str(ROOT / 'build/tomokv'), str(POST))
    value = value.replace('docs/txnorder/runtime-', 'docs/txnorder2/runtime/legacy-' + RUN_ID + '-')
    value = value.replace('build/txnorder/runtime-', 'build/txnorder2/runtime-data-' + RUN_ID + '/legacy-')
    value = value.replace('build/txnorder/owner-data/', 'build/txnorder2/runtime-data-' + RUN_ID + '/owner-data/')
    if value.endswith('pre-armed-server'): value = str(DATA / 'pre-armed-server')
    if value.endswith('post-armed-server'): value = str(DATA / 'post-armed-server')
    if '/proof-drivers/watchlive-' in value:
        value = str(DATA / Path(value).name)
    return value

def stop(process):
    if process is None: return
    try: os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    # A failing client may have left its owned server in this same group.
    try: os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError: pass

def ready(port, process):
    deadline = time.monotonic()+60
    while time.monotonic()<deadline:
        if process.poll() is not None: raise RuntimeError('server exited before PING')
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=1) as sock:
                sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                if sock.recv(32)==b'+PONG\r\n': return
        except OSError: pass
        time.sleep(.05)
    raise RuntimeError('server did not answer PING')

def wrappers():
    DATA.mkdir(parents=True, exist_ok=True)
    import shlex
    for arm,binary in [('pre',PRE),('post',POST)]:
        p=DATA/(arm+'-armed-server')
        p.write_text('#!/bin/bash\nexec taskset -c 64-71 '+shlex.quote(str(binary))+' "$@" --read-local 1\n')
        p.chmod(0o755)
    for mode in ['1s','2s']:
        p=DATA/('watchlive-'+mode)
        p.write_text('#!/bin/bash\nexec taskset -c 64-71 '+shlex.quote(str(POST))+' "$@" --thread-mode '+mode+' --databases 1 --shards 16 --key-lb 0 --client-lb 0 --flip-auto 0 --read-local '+('1' if mode=='1s' else '0')+(' --ratio 6:2' if mode=='2s' else '')+'\n')
        p.chmod(0o755)

def run(index, original, suffix):
    row=transform(original)
    name=f'{index:03d}-'+row['name'].replace('/','_')
    out=OUT/suffix/name
    out.mkdir(parents=True,exist_ok=True)
    result={'index':index,'name':row['name'],'arm':row['arm'],
            'status':'RUNNING','row':row,'started':time.time()}
    receipt=out/'result.json'
    def save(): receipt.write_text(json.dumps(result,indent=2)+'\n')
    save()
    server=client=None
    logs=[]
    try:
        binary=PRE if row['arm']=='pre' else POST
        if row['arm']=='barrier-off': binary=Path(os.environ.get('TXNORDER_BARRIER_BINARY', str(ROOT/'build/txnorder2/barrier-off-final/tomokv')))
        if not binary.exists():
            result.update(status='NOT RUN',reason='missing required arm '+str(binary))
            return
        result['binary']=str(binary);result['sha256']=digest(binary)
        command=row['command']
        if 'tests/watchlive_gate.sh' in command: command[6]='10'
        for arg in command:
            if arg.endswith('.json') and str(ROOT) in arg: Path(arg).parent.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ,TXNFIX_PORT_RANGE='27800-27899',PYTHONUNBUFFERED='1',
                 GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
                 GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli')
        env.update(row.get('env',{}))
        if 'tests/watchlive_gate.sh' in command: env['WATCHLIVE_OUT']=str(out/'boots')
        if 'server' in row:
            argv=row['server']
            argv[3]=str(binary)
            port=int(argv[argv.index('--port')+1]); assert 27800<=port<=27899
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                sock.bind(('127.0.0.1',port))
            if '--dir' in argv:
                directory=Path(argv[argv.index('--dir')+1]); directory.mkdir(parents=True,exist_ok=True)
            else:
                directory=DATA/name; directory.mkdir(parents=True,exist_ok=True)
                argv+=['--dir',str(directory)]
            f=open(out/'server.log','w');logs.append(f)
            server=subprocess.Popen(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
            result['server_pid']=server.pid
            ready(port,server)
        f=open(out/'client.log','w');logs.append(f)
        client=subprocess.Popen(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        limit=7200 if 'differ-' in name or 'watchlive-' in name else 600
        try:
            result['returncode']=client.wait(timeout=limit)
            result['status']='PASS' if result['returncode']==0 else 'FAIL'
        except subprocess.TimeoutExpired:
            result.update(status='TIMEOUT',reason=f'outer lifecycle timeout {limit}s')
    except Exception as exc:
        result.update(status='ERROR',reason=repr(exc))
    finally:
        stop(client);stop(server)
        for f in logs:f.close()
        result['finished']=time.time();save()
        print(index,row['name'],result['status'],result.get('reason',''),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--rows',default='0-214');p.add_argument('--suffix',default='first')
    args=p.parse_args();wrappers()
    rows=json.loads((ROOT/'docs/txnorder/owner-proof-plan.json').read_text())['rows']
    selected=[]
    for token in args.rows.split(','):
        lo,_,hi=token.partition('-');selected.extend(range(int(lo),int(hi or lo)+1))
    for index in selected:run(index,rows[index],args.suffix)
