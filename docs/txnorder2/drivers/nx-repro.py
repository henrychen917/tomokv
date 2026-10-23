#!/usr/bin/env python3
"""Fresh-boot correctness repetitions for the gate's fused NX timeout."""
import hashlib
import argparse
import importlib.util
import json
import os
import re
import signal
import socket
from pathlib import Path
import subprocess
import sys
import time

root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'tests'))
import _lib
spec=importlib.util.spec_from_file_location('runtime',Path(__file__).with_name('runtime.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
binary=root/'build/txnorder2/final-ready/tomokv'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--turns',type=int,default=16)
parser.add_argument('--progress',action='store_true')
parser.add_argument('--debugger',action='store_true')
parser.add_argument('--detach',action='store_true')
parser.add_argument('--allow-attach',action='store_true')
args=parser.parse_args()
label='nx-progress-repro' if args.progress else 'nx-repro'
if args.debugger:label+='-gdb'
if args.detach:label+='-detached'
if args.allow_attach:label+='-owned-attach'
out=root/'docs/txnorder2'/label;out.mkdir(exist_ok=True)
rows=[]
for turn in range(args.turns):
    directory=root/'build/txnorder2'/label/str(turn);directory.mkdir(parents=True,exist_ok=True)
    folder=out/str(turn);folder.mkdir(exist_ok=True)
    cmd=['taskset','-c','88-95',str(binary),'--bind','127.0.0.1','--port','27890',
         '--dir',str(directory),'--save','','--appendonly','no','--databases','1',
         '--shards','16','--thread-mode','1s','--read-local','0','--atomic','1',
         '--key-lb','0','--client-lb','0','--flip-auto','0','--enable-debug-command','yes']
    row=dict(turn=turn,server=cmd,sha256=r.digest(binary));server=client=None;monitor=None;inferior=None
    try:
        with socket.socket() as guard:
            guard.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            guard.bind(('127.0.0.1',27890))
        with (folder/'server.log').open('w') as sf,(folder/'client.log').open('w') as cf:
            launch=['taskset','-c','88-95','gdb','-nx','-q','--interpreter=mi2'] if args.debugger else cmd
            env=dict(os.environ)
            if args.allow_attach:env['LD_PRELOAD']=str(root/'build/txnorder2/ptrace-owned.so')
            row['LD_PRELOAD']=env.get('LD_PRELOAD')
            server=subprocess.Popen(launch,stdin=subprocess.PIPE if args.debugger else None,
                stdout=sf,stderr=subprocess.STDOUT,start_new_session=True,text=args.debugger,env=env)
            if args.debugger:
                for line in ['-gdb-set pagination off','-gdb-set confirm off','-gdb-set mi-async on',
                             '-gdb-set disable-randomization off',
                             '-file-exec-and-symbols '+str(binary),
                             '-exec-arguments '+' '.join(json.dumps(x) for x in cmd[4:]),
                             *(['-break-insert __wrap_main'] if args.detach else []),'-exec-run']:
                    server.stdin.write(line+'\n');server.stdin.flush()
                if args.detach:
                    until=time.monotonic()+10
                    while 'reason="breakpoint-hit"' not in (folder/'server.log').read_text():
                        assert time.monotonic()<until,'startup breakpoint never hit'
                        time.sleep(.05)
                    inferior=int(re.search(r'thread-group-started,id="i1",pid="(\d+)"',
                                          (folder/'server.log').read_text())[1])
                    server.stdin.write('-target-detach\n');server.stdin.flush()
            r.ready(27890,server)
            if args.debugger and inferior is None:
                inferior=int(re.search(r'thread-group-started,id="i1",pid="(\d+)"',
                                      (folder/'server.log').read_text())[1])
            listeners=subprocess.check_output(['ss','-H','-ltnp','sport = :27890'],text=True)
            listener_pids=set(map(int,re.findall(r'pid=(\d+)',listeners)))
            assert listener_pids=={inferior if args.debugger else server.pid},listeners
            row['listener_pids']=sorted(listener_pids)
            command=['taskset','-c','80-87','python3','tests/txn_nx.py','127.0.0.1','27890']
            progress=folder/'progress'
            if args.progress:
                command=['taskset','-c','80-87','python3',str(Path(__file__).with_name('nx-progress-client.py')),
                         '127.0.0.1','27890',str(progress)]
            row['command']=command
            row['server_pid']=server.pid
            client=subprocess.Popen(command,cwd=root,stdout=cf,stderr=subprocess.STDOUT,start_new_session=True)
            if not args.progress:monitor=_lib.Conn('127.0.0.1',27890,timeout=1)
            previous=0;quiet=0;dumped=False;deadline=time.monotonic()+90
            while client.poll() is None and time.monotonic()<deadline:
                try:
                    if args.progress:
                        count=progress.stat().st_mtime_ns if progress.exists() else 0
                        quiet=quiet+1 if count==previous else 0;previous=count
                    else:
                        info=monitor.must('INFO','stats').decode()
                        count=int(next(line.split(':')[1] for line in info.splitlines() if line.startswith('total_commands_processed:')))
                        quiet=quiet+1 if count-previous<5 else 0;previous=count
                except Exception:quiet=10
                if quiet>=(12 if args.progress else 4) and not dumped:
                    dumped=True
                    (folder/'stall-info.txt').write_text(locals().get('info','INFO did not answer'))
                    gdb=['taskset','-c','64-95','gdb','-nx','-batch','-p',str(server.pid),
                         '-ex','set pagination off','-ex','set print elements 256',
                         '-ex','thread apply all bt',
                         '-ex',"p 'tomo_db0::(anonymous namespace)::g_server'",
                         '-ex','source '+str(Path(__file__).with_name('nx-state.gdb')),'-ex','generate-core-file '+str(directory/'stall.core'),'-ex','detach']
                    if args.debugger:
                        server.stdin.write(('-target-attach '+str(inferior) if args.detach else '-exec-interrupt')+'\n')
                        server.stdin.flush();time.sleep(.5)
                        for line in ['set print elements 32','thread apply all bt full',
                                     'source '+str(Path(__file__).with_name('nx-state.gdb'))]:
                            server.stdin.write('-interpreter-exec console '+json.dumps(line)+'\n')
                        server.stdin.write('-exec-continue\n');server.stdin.flush()
                    else:
                        with (folder/'stall-gdb.log').open('w') as gf:
                            row['gdb_exit']=subprocess.run(gdb,stdout=gf,stderr=subprocess.STDOUT,timeout=45).returncode
                time.sleep(.25)
            row['exit_code']=client.wait(timeout=5)
            row['dumped']=dumped
    except Exception as exc:row['error']=repr(exc)
    finally:
        if monitor:monitor.close()
        if inferior:
            try:os.kill(inferior,signal.SIGKILL)
            except ProcessLookupError:pass
        r.stop(client);r.stop(server)
    rows.append(row);(out/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(turn,row.get('exit_code',row.get('error')),row.get('dumped'),flush=True)
    if row.get('exit_code')!=0:break
