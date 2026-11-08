#!/usr/bin/env python3
"""AOF blocking/EXEC crash witnesses; each boot owns its port and a fresh image.

The existing ACK_WINDOW hook stops a non-writer owner before publication. A
different IO thread must remain responsive. Kill inside that hold, recover a
copy, then repeat with release/ack/kill and verify the acknowledged mutation.
"""
import argparse
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time

from persistfix import Run as PersistenceRun, encode, guard_port, wait_for


CASES = ('blpop_now', 'blpop_wake', 'brpop', 'blmpop', 'bzpopmin', 'bzpopmax',
         'bzmpop', 'xreadgroup_now', 'xreadgroup_wake',
         'exec_publish', 'exec_spublish', 'exec_subscribe')


class Run(PersistenceRun):
    def __init__(self, args):
        super().__init__(args)
        self.artifact_root = self.root
        self.env = {}

    def boot(self, hook=True, image=None):
        self.boots += 1
        self.root = self.artifact_root / f'boot-{self.boots}'
        self.root.mkdir()
        if image:
            shutil.copytree(image / 'appendonlydir', self.root / 'appendonlydir')
        self.log_path = self.root / 'server.log'
        self.log = self.log_path.open('xb')
        self.exit_status = None
        self.identity = dict(ready=False, log=str(self.log_path))
        guard_port(self.args.port)
        env = dict(os.environ, LC_ALL='C', **self.env)
        env.pop('TOMO_AOF_ACK_WINDOW', None)
        if hook:
            env['TOMO_AOF_ACK_WINDOW'] = str(self.window.resolve())
        argv = ['taskset', '-c', self.args.cores, str(self.args.binary.resolve()),
                '--bind', '127.0.0.1', '--port', str(self.args.port), '--shards', '16',
                '--protected-mode', 'no', '--thread-mode', self.args.mode,
                '--appendonly', 'yes', '--appendfsync', 'always', '--save', '',
                '--auto-aof-rewrite-percentage', '0', '--enable-debug-command', 'yes',
                '--key-lb', '0', '--client-lb', '0',
                '--dir', str(self.root.resolve()), '--net-io', self.args.net_io]
        if self.args.mode == '2s':
            argv += ['--ratio', self.args.ratio]
        self.process = subprocess.Popen(argv, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.identity.update(pid=self.process.pid, argv=argv)
        self.save_identity()
        self.record('spawn', argv=argv)
        wait_for(self.ready, 'owned server did not become ready', 30)
        return self.ready_client

    def on_io(self, tid):
        for _ in range(128):
            client = self.client()
            if client.cmd('DEBUG', 'IO-THREAD') == tid:
                return client
            client.close()
            self.clients.remove(client)
        raise AssertionError(f'could not place connection on IO {tid}')

    def clear_window(self):
        for suffix in ('entered', 'release', 'kill'):
            self.marker(suffix).unlink(missing_ok=True)

    def entered(self):
        def complete_marker():
            return self.marker('entered').exists() and len(self.marker('entered').read_text().split()) == 2
        wait_for(complete_marker, 'pre-post window never opened')
        return tuple(map(int, self.marker('entered').read_text().split()))

    def kill(self, in_window=False):
        image = self.root
        if in_window:
            self.marker('kill').touch()
        else:
            self.process.kill()
        self.reap(-signal.SIGKILL)
        return image


def info(client, section):
    return dict(line.split(':', 1) for line in client.cmd('INFO', section).decode().splitlines()
                if ':' in line)


def plan(case, key):
    if case.startswith('xreadgroup'):
        return ('XREADGROUP', 'GROUP', 'g', 'c', 'BLOCK', 0, 'STREAMS', key, '>'), \
            ('XADD', key, '1-1', 'f', 'v'), [[key.encode(), [[b'1-1', [b'f', b'v']]]]]
    if case.startswith('exec_'):
        return None, ('RPUSH', key, 'job'), None
    table = {
        'blpop_now': (('BLPOP', key, 0), [key.encode(), b'job']),
        'blpop_wake': (('BLPOP', key, 0), [key.encode(), b'job']),
        'brpop': (('BRPOP', key, 0), [key.encode(), b'job']),
        'blmpop': (('BLMPOP', 0, 1, key, 'LEFT', 'COUNT', 1), [key.encode(), [b'job']]),
        'bzpopmin': (('BZPOPMIN', key, 0), [key.encode(), b'job', b'1']),
        'bzpopmax': (('BZPOPMAX', key, 0), [key.encode(), b'job', b'1']),
        'bzmpop': (('BZMPOP', 0, 1, key, 'MIN', 'COUNT', 1), [key.encode(), [[b'job', b'1']]]),
    }
    command, reply = table[case]
    producer = ('ZADD', key, 1, 'job') if case.startswith('bz') else ('RPUSH', key, 'job')
    return command, producer, reply


def observe(client, case, key):
    if case.startswith('xreadgroup'):
        return client.cmd('XPENDING', key, 'g')[0]
    if case.startswith('bz'):
        return client.cmd('ZRANGE', key, 0, -1)
    return client.cmd('LRANGE', key, 0, -1)


def lifecycle(run, ctrl):
    # No journal record: both an empty timeout and a probe error must still finish.
    assert ctrl.cmd('BLPOP', 'aofblock:timeout', .02) is None
    assert ctrl.cmd('SET', 'aofblock:wrongtype', 'x') == b'OK'
    ctrl.sock.sendall(encode('BLPOP', 'aofblock:wrongtype', 0))
    assert ctrl.stream.readline().startswith(b'-WRONGTYPE ')
    assert ctrl.cmd('PING') == b'PONG', 'exactly one error reply'
    for disconnect in (False, True):
        victim = run.on_io(0)
        ident = victim.cmd('CLIENT', 'ID')
        victim.sock.sendall(encode('BLPOP', 'aofblock:cancel', 0))
        wait_for(lambda: int(info(ctrl, 'clients')['blocked_clients']) == 1, 'waiter did not park')
        if disconnect:
            victim.close()
            run.clients.remove(victim)
        else:
            assert ctrl.cmd('CLIENT', 'UNBLOCK', ident, 'TIMEOUT') == 1
            assert victim.read() is None
            assert victim.cmd('PING') == b'PONG', 'exactly one cancellation reply'
        wait_for(lambda: int(info(ctrl, 'clients')['blocked_clients']) == 0, 'waiter was stranded')


def exercise(args):
    run = Run(args)
    evidence = []
    try:
        ctrl = run.boot()
        # Enumerate the gate's actual IO geometry; the largest IO id owns the writer.
        tids = {run.client().cmd('DEBUG', 'IO-THREAD') for _ in range(48)}
        writer = max(tids)
        assert 0 in tids and writer != 0, f'need independent IO and writer: {tids}'
        ctrl = run.on_io(0)
        keys = [f'persistfix:window:aofblock:{args.case}:{i}' for i in range(64)]
        owners = ctrl.cmd('DEBUG', 'SHARDS', *keys)
        key, owner = next((k, v[1]) for k, v in zip(keys, owners) if v[1] not in (0, writer))
        command, producer, expected = plan(args.case, key)
        wake = args.case.endswith('_wake')
        is_exec = args.case.startswith('exec_')
        run.marker('release').touch()
        if args.case.startswith('xreadgroup'):
            assert ctrl.cmd('XGROUP', 'CREATE', key, 'g', '0', 'MKSTREAM') == b'OK'
        if not wake and not is_exec:
            assert ctrl.cmd(*producer) in (1, b'1-1')
        run.clear_window()

        def trigger(ctrl):
            victim = run.on_io(0)
            pushing = None
            if is_exec:
                assert victim.cmd('MULTI') == b'OK'
                assert victim.cmd('RPUSH', key, 'job') == b'QUEUED'
                verb = args.case.removeprefix('exec_').upper()
                cmd = (verb, 'aofblock:channel') + (() if verb == 'SUBSCRIBE' else ('message',))
                assert victim.cmd(*cmd) == b'QUEUED'
                victim.sock.sendall(encode('EXEC'))
            else:
                victim.sock.sendall(encode(*command))
                if wake:
                    wait_for(lambda: int(info(ctrl, 'clients')['blocked_clients']) == 1,
                             'blocking operation did not park')
                    pushing = run.on_io(0)
                    pushing.sock.sendall(encode(*producer))
            entered_owner, entered_writer = run.entered()
            assert (entered_owner, entered_writer) == (owner, writer), 'wrong owner held'
            return victim, pushing

        victim, pushing = trigger(ctrl)
        early = bool(select.select([victim.sock], [], [], .25)[0])
        reply = victim.read() if early else None
        if early and not is_exec:
            assert reply == expected, f'early reply was not the pop: {reply!r}'
        crash = run.kill(in_window=True)
        run.clear_window()
        ctrl = run.boot(image=crash)
        before = observe(ctrl, args.case, key)
        initial = 0 if args.case.startswith('xreadgroup') else ([] if wake or is_exec else [b'job'])
        assert before == initial, f'pre-post crash image is wrong: {before!r}'
        evidence.append(dict(stage='held-kill-recover', early=early, reply=repr(reply),
                             recovered=repr(before), owner=owner, writer=writer))
        assert not early, 'acknowledged mutation was rolled back by in-window SIGKILL'

        ctrl = run.on_io(0)
        victim, pushing = trigger(ctrl)
        assert not select.select([victim.sock], [], [], .1)[0], 'second hold leaked a reply'
        run.marker('release').touch()
        reply = victim.read()
        if not is_exec:
            assert reply == expected, f'wrong pop reply: {reply!r}'
        else:
            assert isinstance(reply, list) and reply[0] == 1, f'wrong EXEC reply: {reply!r}'
        crash = run.kill()
        run.clear_window()
        ctrl = run.boot(hook=False, image=crash)
        after = observe(ctrl, args.case, key)
        wanted = 1 if args.case.startswith('xreadgroup') else ([b'job'] if is_exec else [])
        assert after == wanted, f'acknowledged mutation lost/redelivered: {after!r}'
        if args.case.startswith('xreadgroup'):
            assert ctrl.cmd('XREADGROUP', 'GROUP', 'g', 'c2', 'STREAMS', key, '>') is None
        evidence.append(dict(stage='release-ack-kill-recover', reply=repr(reply), recovered=repr(after)))
        lifecycle(run, ctrl)
        run.process.terminate()
        run.reap(0)
        print(f'PASS aofblock {args.case} {args.mode} {args.net_io}: {evidence}', flush=True)
    finally:
        (run.artifact_root / 'witness.json').write_text(json.dumps(evidence, indent=2) + '\n')
        run.marker('release').touch()
        run.cleanup()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--net-io', choices=('epoll', 'uring'), required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--case', choices=CASES, required=True)
    return parser.parse_args()


if __name__ == '__main__':
    exercise(arguments())
