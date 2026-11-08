#!/usr/bin/env python3
"""Off-gate preloaded-fsync ordering and slow-final-sync witnesses.

Build shim: gcc -O2 -shared -fPIC tools/aofblock_fsyncdelay.c -o build/aofblock/fsyncdelay.so -ldl
Only epoll is discriminating for preloaded ordering: a shim at uring submit also
delays reaping the previous fsync. Shutdown is checked on either engine.
"""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from aofblock import Run, encode, wait_for


class MaskedWindow(AssertionError):
    pass


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--shim', type=Path, required=True)
    p.add_argument('--mode', choices=('1s', '2s'), required=True)
    p.add_argument('--net-io', choices=('epoll', 'uring'), default='epoll')
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--case', choices=('exec_publish', 'exec_spublish', 'exec_subscribe',
                                    'function_load', 'function_delete', 'function_flush',
                                    'function_restore', 'shutdown'), required=True)
    p.add_argument('--expect', choices=('safe', 'early', 'abort'), required=True)
    p.add_argument('--channel', default='aofblock:channel')
    return p.parse_args()


def attempt(args):
    run = Run(args)
    control = run.artifact_root / 'sync'
    log = run.artifact_root / 'sync.log'
    run.env = dict(LD_PRELOAD=str(args.shim.resolve()), AOFSHIM_LOG=str(log.resolve()),
                   AOFSHIM_DELAY_MS='3500')
    if args.case != 'shutdown':
        assert args.net_io == 'epoll', 'uring submit shim cannot distinguish the stale gate'
        run.env['AOFSHIM_CONTROL'] = str(control.resolve())
    evidence = dict(case=args.case, mode=args.mode, engine=args.net_io, expected=args.expect)
    try:
        run.boot(hook=False)
        victim, older, ping = [run.on_io(0) for _ in range(3)]
        if args.case == 'shutdown':
            assert victim.cmd('SET', 'aofblock:shutdown', 'durable') == b'OK'
            stamp = time.monotonic()
            run.process.terminate()
            rc = run.process.wait(timeout=15)
            elapsed = time.monotonic() - stamp
            text = run.log_path.read_text()
            evidence.update(status=rc, elapsed=elapsed, shutdown_log=text[-5000:])
            assert rc == (0 if args.expect == 'safe' else -signal.SIGABRT), evidence
            if args.expect == 'safe':
                assert elapsed >= 3.5, 'final sync delay did not fire'
                assert 'waiting for final AOF drain/sync bound_ms=10000' in text, text
                image = run.root
                run.reap(0)
                run.env.clear()
                recovered = run.boot(hook=False, image=image)
                assert recovered.cmd('GET', 'aofblock:shutdown') == b'durable'
                run.process.terminate()
                run.reap(0)
        else:
            library = b"#!lua name=aofblock\nredis.register_function('aofblock', function() return 1 end)"
            if args.case != 'function_load' and args.case.startswith('function_'):
                assert victim.cmd('FUNCTION', 'LOAD', library) == b'aofblock'
            dump = victim.cmd('FUNCTION', 'DUMP') if args.case == 'function_restore' else None
            if dump:
                assert victim.cmd('FUNCTION', 'FLUSH') == b'OK'
            if args.case.startswith('exec_'):
                assert victim.cmd('MULTI') == b'OK'
                assert victim.cmd('SET', 'aofblock:transaction', 'durable') == b'QUEUED'
                verb = args.case.removeprefix('exec_').upper()
                command = (verb, args.channel) + (() if verb == 'SUBSCRIBE' else ('message',))
                assert victim.cmd(*command) == b'QUEUED'
                subject = ('EXEC',)
            else:
                subject = {'function_load': ('FUNCTION', 'LOAD', library),
                           'function_delete': ('FUNCTION', 'DELETE', 'aofblock'),
                           'function_flush': ('FUNCTION', 'FLUSH'),
                           'function_restore': ('FUNCTION', 'RESTORE', dump)}[args.case]
            Path(str(control) + '.armed').touch()
            older.sock.sendall(encode('SET', 'aofblock:older', 'value'))
            wait_for(lambda: Path(str(control) + '.1.entered').exists(), 'older fsync not held')
            ping.sock.sendall(encode('PING'))
            assert not select.select([ping.sock], [], [], .15)[0], 'older gate was not held'
            victim.sock.sendall(encode(*subject))
            # Give the subject a whole IO/executor round while the old fsync is stopped.
            assert not select.select([victim.sock], [], [], .15)[0], 'reply before older fsync'
            Path(str(control) + '.1.release').touch()
            wait_for(lambda: Path(str(control) + '.2.entered').exists(), 'subject sync not held')
            assert ping.read() == b'PONG', 'old gate target must be satisfied'
            early = bool(select.select([victim.sock], [], [], .2)[0])
            reply = victim.read() if early else None
            evidence.update(early=early, early_reply=repr(reply), sync2_held=True)
            Path(str(control) + '.armed').unlink()
            if not early:
                reply = victim.read()
            if args.expect == 'early' and not early:
                raise MaskedWindow(evidence)
            assert early == (args.expect == 'early'), evidence
            if args.case.startswith('exec_'):
                assert reply[0] == b'OK', reply
            else:
                assert reply == (b'aofblock' if args.case == 'function_load' else b'OK'), reply
            assert older.read() == b'OK'
            run.process.terminate()
            run.reap(0)
        print(json.dumps(evidence, sort_keys=True), flush=True)
    finally:
        Path(str(control) + '.armed').unlink(missing_ok=True)
        (run.artifact_root / 'ordering.json').write_text(json.dumps(evidence, indent=2) + '\n')
        run.cleanup()


if __name__ == '__main__':
    args = arguments()
    for number in range(8):
        try:
            attempt(args)
            break
        except MaskedWindow:
            if number == 7:
                raise
            print(f'gate window masked; rearming on fresh server, attempt {number + 2}', flush=True)
