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

def run_file(args, tree, unit, only=None, extra=(), server_args=()):
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
    command += list(server_args)
    client=['taskset','-c',args.cores,'./runtest','--host','127.0.0.1','--port',str(port),
            '--singledb','--clients','1','--baseport',str(args.baseport),'--portcount','1',
            '--single',unit,'--durable','--timeout',str(args.idle_timeout),
            '--dont-clean','--dont-pre-clean']
    if only:
        for name in only: client+=['--only',name]
    client+=list(extra)
    start=time.monotonic();server=None;test=None;failure=None;rc=None;layout_attempts=[]
    with (folder/'server.log').open('w') as sl, (folder/'suite.log').open('w') as tl:
        try:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1',port))
            # The unchanged SMOVE assertion names fixed keys. TomoKV randomizes
            # their placement at boot; only its same-shard branch exposed this
            # WATCH regression. Reroll fresh boots, never skip an unarmed test.
            arm_smove = (getattr(args, 'arm_smove', False) and
                         args.mode != 'redis' and unit == 'unit/type/set')
            for attempt in range(128 if arm_smove else 1):
                server=subprocess.Popen(command,stdout=sl,stderr=subprocess.STDOUT,start_new_session=True)
                for _ in range(150):
                    if server.poll() is not None: raise RuntimeError('server exited during boot')
                    try:
                        c=Conn('127.0.0.1',port); reply=c.cmd('PING')
                        if reply=='PONG' or reply==b'PONG': break
                        c.close()
                    except (OSError,RuntimeError): pass
                    time.sleep(.05)
                else: raise RuntimeError('server not ready')
                armed=True
                try:
                    if arm_smove:
                        shards=[c.cmd('DEBUG','SHARD',key) for key in ('srcset{t}','dstset{t}')]
                        assert all(isinstance(s,int) and 0 <= s < 16 for s in shards), shards
                        armed=shards[0]==shards[1]
                        layout_attempts.append(dict(attempt=attempt+1,shards=shards,armed=armed))
                finally: c.close()
                if armed: break
                stop(server);server=None
            else: raise RuntimeError('SMOVE same-shard arming failed after 128 fresh boots')
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
             server_exit=server.returncode if server else None,smove_layout_attempts=layout_attempts,events=observed)
    (folder/'result.json').write_text(json.dumps(row,indent=2)+'\n')
    return row

def setup_signature(data):
    """(command, reply) of an err raised by start_server-block code outside any test.

    --durable reports it as an unnamed err and abandons that block. It cannot be
    skipped by name, so the manifest names it exactly: the failing Tcl command
    and the server's reply line."""
    lines = [line.strip() for line in data.split('\n')]
    commands = []
    for index, line in enumerate(lines[:-1]):
        if line in ('while executing', 'invoked from within'):
            command = lines[index + 1]
            if len(command) > 1 and command[0] == command[-1] == '"':
                command = command[1:-1]
            if not command.startswith(('[srv', 'error ', 'uplevel')):
                commands.append(command)
    reply = next((line for line in lines[1:] if line.startswith(('ERR ', 'WRONGTYPE', 'NOSCRIPT', 'BUSY', 'OOM'))),
                 lines[0])
    return (commands[0] if commands else '', reply)

def setup_errors(row):
    return Counter(setup_signature(e['data']) for e in row['events']
                   if e['status'] == 'err' and not e['test'].split(' in tests/')[0])

def validate_passing(row, expected, known_setup_errors=()):
    actual = [e['test'] for e in row['events'] if e['status'] == 'ok']
    known = Counter({(k['command'], k['reply']): k['count'] for k in known_setup_errors})
    observed = setup_errors(row)
    # Exactly the named block-setup errors, no other failure of any kind. runtest
    # exits 1 whenever it recorded any failure, including a named setup error.
    expected_rc = 1 if observed else 0
    if (not expected or not actual or Counter(actual) != Counter(expected) or observed != known or
            row['failed'] != sum(observed.values()) or row['error'] or not row['complete'] or
            row['exit_code'] != expected_rc):
        raise ValueError('passing subset failed, incomplete, or assertion inventory changed')

def load_manifest(path, redis_root, inventory):
    """The frozen subset: upstream bytes, required passes and NAMED known failures."""
    manifest=json.loads(Path(path).read_text())
    if not manifest.get('files'): raise ValueError('empty passing subset')
    for name, expected in manifest['support'].items():
        if sha(Path(redis_root) / name) != expected:
            raise ValueError('upstream support changed: ' + name)
    for unit, spec in manifest['files'].items():
        if inventory.get(unit)!=spec['sha256']:
            raise ValueError(f'upstream changed: {unit}')
        # A known failure is named, never silently dropped: it may not also be a
        # required pass, and every required file has at least one pass.
        required = {name.split(' in tests/')[0] for name in spec['passed_tests']}
        if not spec['passed_tests'] or set(spec.get('skip_tests', ())) & required:
            raise ValueError(f'manifest file has no required pass or skips a required test: {unit}')
        # The upstream histogram file assumes Redis's default yes. TomoKV's
        # owner-selected default is no, so this explicit, bound file setup
        # enables the feature under test without editing upstream assertions.
        server_args = spec.get('server_args', [])
        if server_args and (unit != 'unit/latency-monitor' or
                            server_args != ['--latency-tracking', 'yes']):
            raise ValueError(f'invalid server arguments: {unit}')
        # Only tag exclusions (file-level setup TomoKV cannot run); never a
        # second selection such as --only/--skipfile that could hide a test.
        extra = spec.get('extra_args', [])
        if len(extra) % 2 or any(flag != '--tags' for flag in extra[::2]):
            raise ValueError(f'invalid extra runtest arguments: {unit}')
        for known in spec.get('known_setup_errors', ()):
            if (set(known) != {'command', 'reply', 'count'} or not known['command'] or not known['reply'] or
                    type(known['count']) is not int or known['count'] < 1):
                raise ValueError(f'invalid known setup error: {unit}')
    return manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--redis-root',type=Path,default=Path('/home/user/Projects/redis'))
    p.add_argument('--binary',type=Path,required=True);p.add_argument('--mode',choices=['1s','2s','redis'],required=True)
    p.add_argument('--cores',required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--baseport',type=int,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--only-files',default='')
    p.add_argument('--idle-timeout',type=int,default=60);p.add_argument('--file-timeout',type=int,default=240)
    p.add_argument('--resume',action='store_true');p.add_argument('--manifest',type=Path)
    p.add_argument('--controller-port', type=int)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--arm-smove', action='store_true')
    args=p.parse_args();args.output=args.output.resolve();args.binary=args.binary.resolve();args.output.mkdir(parents=True,exist_ok=True)
    tree=args.output/'checkout';prepare(args.redis_root,tree,controller_port=args.controller_port)
    files=sorted([*args.redis_root.glob('tests/unit/**/*.tcl'),*args.redis_root.glob('tests/integration/**/*.tcl')])
    inventory={str(f.relative_to(args.redis_root/'tests')).removesuffix('.tcl'):sha(f) for f in files}
    units=list(inventory)
    if args.only_files: units=args.only_files.split(',')
    if args.manifest:
        manifest=load_manifest(args.manifest, args.redis_root, inventory); units=list(manifest['files'])
    report=dict(mode=args.mode,binary_sha256=sha(args.binary),redis_version=(args.redis_root/'src/version.h').read_text(),
                inventory=inventory,rows=[])
    for unit in units:
        path=args.output/unit/'result.json'
        extra=[]
        server_args=[]
        if args.manifest:
            spec=manifest['files'][unit]
            server_args=spec.get('server_args', [])
            skipfile=args.output/unit/'skip.txt'; skipfile.parent.mkdir(parents=True,exist_ok=True)
            skipfile.write_text(''.join(name+'\n' for name in sorted(spec.get('skip_tests', ()))), encoding='utf-8')
            extra=['--skipfile',str(skipfile),*spec.get('extra_args',[])]
        if args.resume and path.exists(): row=json.loads(path.read_text())
        else: row=run_file(args,tree,unit,extra=extra,server_args=server_args)
        if args.manifest:
            row['skip_tests']=sorted(spec.get('skip_tests', ()))
            row['setup_errors']=[dict(command=c, reply=r, count=n) for (c, r), n in sorted(setup_errors(row).items())]
            try: validate_passing(row, spec['passed_tests'], spec.get('known_setup_errors', ()))
            except ValueError as error: row['error'] = '; '.join(filter(None, (row['error'], str(error))))
        report['rows'].append(row)
        (args.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(f"{args.mode} {unit}: {row['passed']} pass {row['failed']} fail {row['skipped']} skip rc={row['exit_code']} complete={row['complete']}",flush=True)
    if sha(args.binary) != report['binary_sha256']: raise ValueError('candidate changed during suite')
    # With a manifest, validate_passing has already accounted for each named
    # setup error and recorded any other failure as row['error'].
    def failed(r):
        if args.manifest:
            return bool(r['error'])
        return r['failed'] or r['error'] or not r['complete'] or r['exit_code']
    return int(any(failed(r) for r in report['rows']))
if __name__=='__main__':sys.exit(main())
