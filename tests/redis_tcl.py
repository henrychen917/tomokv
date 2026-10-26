#!/usr/bin/env python3
"""Run Redis's unchanged Tcl tests in a private external-server checkout."""
import argparse, base64, hashlib, json, os, shutil, signal, socket, subprocess, sys, time
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
from _lib import Conn

HOOK = r'''
# Receipt observer only: forwards every original packet unchanged.
rename send_data_packet harness5_send_data_packet
proc send_data_packet {fd status data {elapsed 0}} {
    if {$::client} {
        set out [open $::env(HARNESS5_TCL_EVENTS) a]
        set fields [list $status $::curfile $::cur_test $data $elapsed]
        set encoded {}
        foreach value $fields {
            lappend encoded [binary encode base64 -maxlen 0 [encoding convertto utf-8 $value]]
        }
        puts $out [join $encoded "\t"]
        close $out
    }
    harness5_send_data_packet $fd $status $data $elapsed
}
'''

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def stop(process):
    if process is None: return
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
    # runtest can exit before its Tcl child after an exception.
    try: os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError: pass

def prepare(source, dest, *, controller_port=None):
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copytree(source/'tests', dest/'tests', ignore=shutil.ignore_patterns('tmp','*.so','*.o'))
    shutil.copy2(source/'runtest',dest/'runtest')
    shutil.copy2(source/'redis.conf',dest/'redis.conf')
    (dest/'src').mkdir()
    for name in ('redis-server','redis-cli','redis-check-rdb','redis-check-aof'):
        if (source/'src'/name).exists(): shutil.copy2(source/'src'/name,dest/'src'/name)
    helper=dest/'tests/test_helper.tcl'
    text=helper.read_text()
    # Upstream's default discovery omits moduleapi; include the supplied files.
    text=text.replace('    unit/type\n', '    unit/type\n    unit/moduleapi\n',1)
    marker='if {$::client} {\n    if {[catch { test_client_main'
    assert marker in text
    if controller_port is not None:
        # The gate owns a three-port slot. Do not scan into another job's slot.
        text = text.replace('find_available_port [expr {$::baseport - 32}] 32',
                            f'find_available_port {controller_port} 1', 1)
    helper.write_text(text.replace(marker,HOOK+'\n'+marker,1))
    (dest/'tests/tmp').mkdir(exist_ok=True)

def events(path):
    result=[]
    if path.exists():
        for line in path.read_text().splitlines():
            values=[base64.b64decode(v).decode('utf-8','replace') for v in line.split('\t')]
            if len(values)!=5: raise ValueError('incomplete Tcl event')
            result.append(dict(zip(('status','file','test','data','milliseconds'),values)))
    return result

def counts(observed, unit):
    result = dict(passed=0, failed=0, skipped=0, teardown_exceptions=0)
    complete = False
    for event in observed:
        status = event['status']
        if status == 'done' and event['data'] == unit:
            complete = True
        # Upstream closes the controller socket after done; its client reports
        # this EOF exception even on Redis itself. Preserve it, do not count it
        # as a failed assertion. Any exception before done still fails the file.
        elif (complete and status == 'exception' and
              'expected non-negative integer but got ""' in event['data'] and
              'read $::test_server_fd $bytes' in event['data']):
            result['teardown_exceptions'] += 1
        elif status in ('err', 'exception'):
            result['failed'] += 1
        elif status == 'ok': result['passed'] += 1
        elif status in ('skip', 'ignore'): result['skipped'] += 1
    return result, complete

def run_file(args, tree, unit, only=None):
    folder=args.output/unit
    folder.mkdir(parents=True,exist_ok=True)
    event_path=folder/'events.tsv'
    event_path.unlink(missing_ok=True)
    data=folder/'data';data.mkdir(exist_ok=True)
    port=args.port
    command=['taskset','-c',args.cores,str(args.binary),'--port',str(port),'--bind','127.0.0.1',
             '--save','','--appendonly','no','--dir',str(data),'--enable-debug-command','yes']
    if args.mode!='redis':
        command+=['--thread-mode',args.mode,'--shards','16','--databases','16']
        if args.mode=='2s': command+=['--ratio', getattr(args, 'ratio', '6:2')]
    else: command+=['--enable-module-command','yes']
    client=['taskset','-c',args.cores,'./runtest','--host','127.0.0.1','--port',str(port),
            '--singledb','--clients','1','--baseport',str(args.baseport),'--portcount','1',
            '--single',unit,'--durable','--timeout',str(args.idle_timeout),
            '--dont-clean','--dont-pre-clean']
    if only:
        for name in only: client+=['--only',name]
    start=time.monotonic();server=None;test=None;failure=None;rc=None
    with (folder/'server.log').open('w') as sl, (folder/'suite.log').open('w') as tl:
        try:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1',port))
            server=subprocess.Popen(command,stdout=sl,stderr=subprocess.STDOUT,start_new_session=True)
            for _ in range(150):
                if server.poll() is not None: raise RuntimeError('server exited during boot')
                try:
                    c=Conn('127.0.0.1',port); reply=c.cmd('PING');c.close()
                    if reply=='PONG' or reply==b'PONG': break
                except (OSError,RuntimeError): pass
                time.sleep(.05)
            else: raise RuntimeError('server not ready')
            # gate.sh uses LC_ALL=C. Upstream files contain UTF-8 test names;
            # bind their decoding so the same assertion inventory survives it.
            test=subprocess.Popen(client,cwd=tree,env=dict(os.environ,HARNESS5_TCL_EVENTS=str(event_path),
                                  LANG='C.UTF-8', LC_ALL='C.UTF-8'),
                                  stdout=tl,stderr=subprocess.STDOUT,start_new_session=True)
            try: rc=test.wait(timeout=args.file_timeout)
            except subprocess.TimeoutExpired: failure='file deadline exceeded';rc=124
        except Exception as exc: failure=f'{type(exc).__name__}: {exc}'
        finally:
            stop(test);stop(server)
    observed=events(event_path)
    totals, complete = counts(observed, unit)
    row=dict(file=unit,mode=args.mode,**totals,complete=complete,exit_code=rc,error=failure,
             seconds=time.monotonic()-start,server_argv=command,suite_argv=client,
             server_exit=server.returncode if server else None,events=observed)
    (folder/'result.json').write_text(json.dumps(row,indent=2)+'\n')
    return row

def validate_passing(row, expected):
    actual = [e['test'] for e in row['events'] if e['status'] == 'ok']
    if (not expected or not actual or Counter(actual) != Counter(expected) or row['failed'] or
            row['error'] or not row['complete'] or row['exit_code']):
        raise ValueError('passing subset failed, incomplete, or assertion inventory changed')

def main():
    p=argparse.ArgumentParser();p.add_argument('--redis-root',type=Path,default=Path('/home/user/Projects/redis'))
    p.add_argument('--binary',type=Path,required=True);p.add_argument('--mode',choices=['1s','2s','redis'],required=True)
    p.add_argument('--cores',required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--baseport',type=int,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--only-files',default='')
    p.add_argument('--idle-timeout',type=int,default=60);p.add_argument('--file-timeout',type=int,default=240)
    p.add_argument('--resume',action='store_true');p.add_argument('--manifest',type=Path)
    p.add_argument('--controller-port', type=int)
    p.add_argument('--ratio', default='6:2')
    args=p.parse_args();args.output=args.output.resolve();args.binary=args.binary.resolve();args.output.mkdir(parents=True,exist_ok=True)
    tree=args.output/'checkout';prepare(args.redis_root,tree,controller_port=args.controller_port)
    files=sorted([*args.redis_root.glob('tests/unit/**/*.tcl'),*args.redis_root.glob('tests/integration/**/*.tcl')])
    inventory={str(f.relative_to(args.redis_root/'tests')).removesuffix('.tcl'):sha(f) for f in files}
    units=list(inventory)
    if args.only_files: units=args.only_files.split(',')
    if args.manifest:
        manifest=json.loads(args.manifest.read_text()); units=list(manifest['files'])
        if not units: raise ValueError('empty passing subset')
        for name, expected in manifest['support'].items():
            if sha(args.redis_root / name) != expected:
                raise ValueError('upstream support changed: ' + name)
        for unit in units:
            if inventory[unit]!=manifest['files'][unit]['sha256']:
                raise ValueError(f'upstream changed: {unit}')
    report=dict(mode=args.mode,binary_sha256=sha(args.binary),redis_version=(args.redis_root/'src/version.h').read_text(),
                inventory=inventory,rows=[])
    for unit in units:
        path=args.output/unit/'result.json'
        if args.resume and path.exists(): row=json.loads(path.read_text())
        else: row=run_file(args,tree,unit)
        if args.manifest:
            try: validate_passing(row, manifest['files'][unit]['passed_tests'])
            except ValueError as error: row['error'] = str(error)
        report['rows'].append(row)
        (args.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(f"{args.mode} {unit}: {row['passed']} pass {row['failed']} fail {row['skipped']} skip rc={row['exit_code']} complete={row['complete']}",flush=True)
    if sha(args.binary) != report['binary_sha256']: raise ValueError('candidate changed during suite')
    return int(any(r['failed'] or r['error'] or not r['complete'] or r['exit_code'] for r in report['rows']))
if __name__=='__main__':sys.exit(main())
