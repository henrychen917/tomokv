"""GDB-only, bounded command-scope PMU diagnostic; no rate or load loop."""
import collections
import ctypes
import fcntl
import gdb
import json
import os
from pathlib import Path
import struct
import subprocess

out = Path(os.environ['WAVE4D_TRACE_OUT'])
config = json.loads((out / 'config.json').read_text())
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from trace_pmu import counters,fds
for command in ('set pagination off','set confirm off','set print thread-events off',
                'set debuginfod enabled off','set breakpoint pending off',
                'handle SIGUSR1 stop nopass','handle SIGPIPE nostop noprint pass'):
    gdb.execute(command)
gdb.execute('starti',to_string=True)
pid=gdb.selected_inferior().pid
(out/'pid').write_text(str(pid))
client=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).with_name('trace_client.py')),str(out)])
rows=[]
try:
    gdb.execute('continue',to_string=True)
    assert (out/'armed.json').exists(), 'client failed to populate and arm'
    names=('xshard_prepare','xshard_execute','xshard_complete','xshard_complete_iofused','xshard_retire','cmd_xshard_only')
    symbols=subprocess.check_output(['nm','-S','-C',config['binary']],text=True)
    breakpoints=[];entries={}
    for name in names:
        full=next(s.split(None,3)[3] for s in symbols.splitlines()
                  if ' T tomo_db0::'+name+'(' in s)
        address=int(gdb.parse_and_eval('(unsigned long)&\''+full+'\''))
        bp=gdb.Breakpoint('*'+hex(address),internal=True)
        breakpoints.append(bp);entries[address]=name
    (out/'go').write_text('go')
    for visit in range(1000):
        gdb.execute('continue',to_string=True)
        pc=int(gdb.parse_and_eval('$pc'))
        if pc not in entries:
            assert (out/'client.json').exists(), 'unexpected stop before completed replies'
            break
        name=entries[pc]
        thread=gdb.selected_thread();tid=thread.ptid[1]
        rsp=int(gdb.parse_and_eval('$rsp'))
        address=int.from_bytes(gdb.selected_inferior().read_memory(rsp,8).tobytes(),'little')
        for bp in breakpoints:bp.enabled=False
        ret=gdb.Breakpoint('*'+hex(address),internal=True,temporary=True)
        ret.thread=thread.global_num
        gdb.execute('set scheduler-locking on')
        fd=counters(tid)
        fcntl.ioctl(fd,0x2403,1);fcntl.ioctl(fd,0x2400,1)
        gdb.execute('continue',to_string=True)
        fcntl.ioctl(fd,0x2401,1)
        assert int(gdb.parse_and_eval('$pc'))==address, 'scope did not return'
        raw=os.read(fd,8*5)
        nr,enabled,running,ins,cycles=struct.unpack('=5Q',raw)
        assert nr==2 and enabled==running and running>0, ('PMU unavailable or multiplexed',raw.hex())
        rows.append(dict(function=name,tid=tid,instructions=ins-1,raw_instructions=ins,cycles=cycles,
                         time_enabled_ns=enabled,time_running_ns=running))
        gdb.execute('set scheduler-locking off')
        for bp in breakpoints:bp.enabled=True
    else:raise AssertionError('bounded diagnostic exceeded 1000 scopes')
    assert client.wait(timeout=20)==0
    proof=json.loads((out/'client.json').read_text())
    assert proof['replies']==config['depth']
    counts=collections.Counter(r['function'] for r in rows)
    assert counts['xshard_prepare']==counts['xshard_retire']==config['depth'], counts
    assert counts['xshard_execute']==config['depth']*8,counts
    assert counts['xshard_complete']+counts['xshard_complete_iofused']>=config['depth']*8,counts
    result=dict(status='PASS',config=config,setup=json.loads((out/'armed.json').read_text()),
                scopes=rows,scope_counts=counts,
                instructions_per_command=sum(r['instructions'] for r in rows)/config['depth'],
                cycles_per_command=sum(r['cycles'] for r in rows)/config['depth'],
                note='User-only PMU from function entry trap to return trap, one retired return breakpoint subtracted (known-count control), inclusive callees; parser, scheduling, network and idle loops excluded. Threads serialized during each scope; cycles are debugger-perturbed, not latency or throughput.')
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
finally:
    for group in fds.values():
        for fd in group:os.close(fd)
    if client.poll() is None:client.terminate();client.wait(timeout=10)
    gdb.execute('set scheduler-locking off')
    gdb.execute('kill',to_string=True)
