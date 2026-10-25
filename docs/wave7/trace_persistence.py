#!/usr/bin/env python3
"""Diagnostic gate jobs; attach only to the owned POST PID at a captured abort."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64,96)))
env=dict(os.environ, LD_PRELOAD=str(ROOT/'build/wave7/abort-trace.so'), WAVE7_ABORT_STOP='1')
for index in range(1,17):
    name=f'persistence-abort-stop-{index}'
    with (ROOT/f'build/wave7/{name}.log').open('w') as log:
        process=subprocess.Popen(['python3','docs/wave7/run_jobs.py',name,'persistfix2_errors'],
                                 env=env, stdout=log, stderr=subprocess.STDOUT)
        captured=set()
        while process.poll() is None:
            gate=ROOT/f'docs/wave7/correctness/{name}/gate.log'
            if gate.exists() and (match:=re.search(r'artifacts: (.+)',gate.read_text())):
                for path in Path(match[1]).rglob('server.log'):
                    text=path.read_text(errors='replace')
                    for pid,tid in re.findall(r'WAVE7_ABORT pid=(\d+) tid=(\d+)',text):
                        if pid in captured:continue
                        assert Path(f'/proc/{pid}/exe').resolve() == ROOT/'build/tomokv'
                        captured.add(pid)
                        output=ROOT/f'docs/wave7/{name}-{pid}-gdb.log'
                        commands=['set pagination off','set print elements 8','set print max-depth 3',
                                  'thread apply all bt 12',
                                  f'python next(t for t in gdb.selected_inferior().threads() if t.ptid[1] == {tid}).switch()',
                                  'bt full 16',
                                  'python f=gdb.newest_frame()\nwhile f and "xshard_retire" not in (f.name() or ""): f=f.older()\nif f: f.select()',
                                  'info args','info locals','p op','p *state','p pool','detach']
                        command=['gdb','-q','-nx','-batch','-p',pid]
                        for text in commands:command+=['-ex',text]
                        try:
                            with output.open('w') as stream:
                                result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=12)
                            print(name,pid,tid,'gdb',result.returncode,flush=True)
                        finally:
                            try:os.kill(int(pid),signal.SIGCONT)
                            except ProcessLookupError:pass
            time.sleep(.025)
        print(name,'job exit',process.returncode,'captured',sorted(captured),flush=True)
        if captured:break
else:raise SystemExit('no stopped abort in bounded complete jobs')
