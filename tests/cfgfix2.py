#!/usr/bin/env python3
"""Round-5 configuration witnesses, through gate.sh's selected-job interface.

CG5.1 follows round5-read/tests/config-gate/live_config.py T5.
SV5.1/2 follow round5-read/tests/cmd-server/probes.py T2--T5.
All children are owned, CPU pinned, and boot with LC_ALL=C. No rate scoring.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import threading
import time
import traceback

import _netfix as n


class Server:
    def __init__(self, a, label, mode, engine, *, config=None, extra=(), directory=None, shards=16):
        self.a, self.label = a, label
        self.directory = (directory or a.output / label).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        binary = a.oracle if mode == 'redis' else a.binary
        cmd = ['taskset', '-c', a.cores, binary]
        if config is not None:
            cmd += [str(config)]
        cmd += ['--bind', '127.0.0.1', '--port', str(a.port), '--save', '',
                '--appendonly', 'no', '--dir', str(self.directory)]
        if mode != 'redis':
            cmd += ['--thread-mode', mode, '--shards', str(shards), '--net-io', engine]
            if mode == '2s':
                cmd += ['--ratio', a.ratio]
        cmd += list(extra)
        self.record = dict(argv=cmd, binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest())
        self.logpath = self.directory / (label + '.log')
        self.log = self.logpath.open('w')
        self.p = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT,
                                  env=dict(os.environ, LC_ALL='C'),
                                  preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
        self.record['pid'] = self.p.pid

    def ready(self, *, may_refuse=False):
        deadline = time.monotonic() + 15
        while self.p.poll() is None and time.monotonic() < deadline:
            try:
                with closing(n.connect(self.a.port)) as c:
                    c.cmd('PING')  # NOAUTH is also a ready listener.
                    return True
            except (OSError, EOFError):
                time.sleep(.02)
        if may_refuse and self.p.poll() is not None:
            return False
        raise AssertionError(('boot failed', self.p.poll(), self.logpath.read_text()[-2000:]))

    def close(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(30)
            except subprocess.TimeoutExpired:
                self.record['forced_kill'] = True
                self.p.kill()
                self.p.wait(5)
        self.log.close()
        self.record['exit_code'] = self.p.returncode
        (self.directory / (self.label + '.json')).write_text(json.dumps(self.record, indent=2) + '\n')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', self.a.port), .1):
                    time.sleep(.02)
            except OSError:
                return
        raise AssertionError('listener survived owned child')

    def __enter__(self):
        try:
            self.ready()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, kind, *unused):
        self.close()
        if kind is None:
            assert self.p.returncode == 0, (self.p.returncode, self.logpath.read_text()[-2000:])


def file_case(a, mode, engine):
    malformed = [
        'user alice on >secret ~* +@all --requirepass ""',
        'save 3600 1 --requirepass ""',
        'latency-tracking-info-percentiles 50 --requirepass ""',
    ]
    results = []
    for i, line in enumerate(malformed):
        label = f'file-{mode}-{engine}-{i}'
        config = a.output / (label + '.conf')
        config.write_text('# line-number control\nrequirepass cg5-required\n' + line + '\n')
        child = Server(a, label, mode, engine, config=config)
        try:
            booted = child.ready(may_refuse=True)
            observation = dict(booted=booted)
            if booted:
                with closing(n.connect(a.port)) as c:
                    observation['unauth_set'] = repr(c.cmd('SET', 'cg5-key', 'value'))
                    observation['requirepass'] = repr(c.cmd('CONFIG', 'GET', 'requirepass'))
        finally:
            child.close()
        text = child.logpath.read_text()
        observation.update(exit_code=child.p.returncode, error=text)
        results.append(observation)
    # A scalar beginning with -- remains a literal password.
    label = f'file-control-{mode}-{engine}'
    config = a.output / (label + '.conf')
    config.write_text('requirepass --requirepass\nuser alice on >secret ~allowed:* &allowed:* +get\n'
                      'save 3600 1\nlatency-tracking-info-percentiles 10 90\n')
    with Server(a, label, mode, engine, config=config):
        with closing(n.connect(a.port)) as c:
            assert str(c.cmd('SET', 'cg5-key', 'value')).startswith('NOAUTH')
            assert c.must('AUTH', '--requirepass') == b'OK'
            assert c.must('SET', 'cg5-key', 'value') == b'OK'
    (a.output / f'file-{mode}-{engine}-observations.json').write_text(json.dumps(results, indent=2))
    assert all(not row['booted'] and row['exit_code'] == 1 for row in results), results
    for line, row in zip(malformed, results):
        if line.startswith('user '):
            # Redis defers unknown command names until ACL initialization.
            assert '--requirepass' in row['error'] and 'ACL' in row['error'], row
            continue
        assert '*** FATAL CONFIG FILE ERROR' in row['error'], row
        assert 'Reading the configuration file, at line 3' in row['error'], row
        assert "'" + line + "'" in row['error'], row
    return dict(rejected=len(malformed), positive_controls=1)


def acl_trial(a, mode, engine, databases, external):
    label = f'acl-{mode}-{engine}-db{databases}-external{external}'
    directory = a.output / label
    directory.mkdir(parents=True, exist_ok=True)
    config, aclfile = directory / 'server.conf', directory / 'users.acl'
    users = ('user default on >bootstrap ~* &* +@all\n'
             'user obsolete on >oldpass ~* &* +@all\n'
             'user rotate on >discard ~old:* &old:* +get\n')
    if external:
        aclfile.write_text(users)
        config.write_text('aclfile ' + str(aclfile) + '\n')
    else:
        config.write_text('requirepass bootstrap\n' + users)
    extra = ['--databases', str(databases)]
    if mode != 'redis' and databases == 16:
        extra += ['--read-local', '1', '--atomic', '1', '--reorder', '1']
    result = dict(databases=databases, external=external)
    with Server(a, label, mode, engine, config=config, extra=extra, directory=directory):
        with closing(n.connect(a.port)) as c:
            c.must('AUTH', 'bootstrap')
            assert c.must('ACL', 'DELUSER', 'obsolete') == 1
            c.must('ACL', 'SETUSER', 'fresh', 'on', '>freshpass', '~fresh:*', '&fresh:*', '+get', '+ping')
            c.must('ACL', 'SETUSER', 'rotate', 'resetpass', '>second', '>third',
                   'resetkeys', '~live:*', 'resetchannels', '&live:*', '-@all', '+get', '+set')
            c.must('ACL', 'SETUSER', 'default', 'resetpass', '>current', '>other')
            before = sorted(c.must('ACL', 'LIST'))
            if external:
                # Only ACL SAVE owns the external file. REWRITE must
                # also discard obsolete inline directives in its input.
                c.must('ACL', 'SAVE')
                acl_bytes = aclfile.read_bytes()
                with config.open('a') as f:
                    f.write('USER obsolete on >oldpass ~* &* +@all\n')
            c.must('CONFIG', 'REWRITE')
            if external:
                assert aclfile.read_bytes() == acl_bytes
                assert not any(line.lower().startswith('user ') for line in config.read_text().splitlines())
            result['before'] = [line.decode() for line in before]
    with Server(a, label + '-restart', mode, engine, config=config, extra=extra, directory=directory):
        with closing(n.connect(a.port)) as c:
            result['auth_current'] = repr(c.cmd('AUTH', 'current'))
            # A failure still retains the exact after-image for PRE.
            if result['auth_current'] != "b'OK'":
                c.must('AUTH', 'bootstrap')
            after = sorted(c.must('ACL', 'LIST'))
            result['after'] = [line.decode() for line in after]
            result['obsolete'] = repr(c.cmd('AUTH', 'obsolete', 'oldpass'))
            result['fresh'] = repr(c.cmd('AUTH', 'fresh', 'freshpass'))
    (directory / "observations.json").write_text(json.dumps(result, indent=2))
    assert result["before"] == result["after"], result
    assert result["auth_current"] == "b'OK'" and result["fresh"] == "b'OK'", result
    assert "WRONGPASS" in result["obsolete"], result
    return result

def acl_case(a, mode, engine):
    results = []
    for databases in (1, 16):
        for external in (False, True):
            try:
                result = acl_trial(a, mode, engine, databases, external)
                results.append(dict(databases=databases, external=external, passed=True, result=result))
            except Exception:
                results.append(dict(databases=databases, external=external, passed=False, error=traceback.format_exc()))
    (a.output / f"acl-{mode}-{engine}-observations.json").write_text(json.dumps(results, indent=2))
    assert all(r["passed"] for r in results), results
    return dict(restart_cases=len(results), exact_registry_roundtrips=len(results))


def latency_case(a, mode, engine):
    """SV5.1: INFO LATENCYSTATS must copy one complete percentile list.

    One writer alternates 512 copies of p10 with 512 copies of p90 while four
    independent readers poll INFO. Any other label list, or a reply that is not
    ASCII text, is a torn read. 1s keeps the gate's 16 shards. 2s uses two
    shards at the gate ratio: with 16 shards the second executor's locked
    validation of its own CONFIG fragments masks the unlocked shard-0 rebuild
    on PRE, so that geometry cannot discriminate.
    """
    results = []
    count, minimum_writes, minimum_seconds = 512, 1600, 2.0
    for databases in (1, 16):
        label = f'latency-{mode}-{engine}-db{databases}'
        extra = ['--latency-tracking', 'yes', '--databases', str(databases)]
        if mode != 'redis' and databases == 16:
            extra += ['--read-local', '1', '--atomic', '1', '--reorder', '1']
        shards = 2 if mode == '2s' else 16
        result = dict(databases=databases, shards=None if mode == 'redis' else shards,
                      writes=0, reads=0, torn=0, corrupt=0, first=None, errors=[])
        with Server(a, label, mode, engine, extra=extra, shards=shards):
            values = [' '.join([value] * count) for value in ('10', '90')]
            with closing(n.connect(a.port)) as c:
                c.must('CONFIG', 'SET', 'latency-tracking-info-percentiles', values[0])
                c.must('PING')
                if mode != 'redis':
                    shown = dict(zip(*[iter(c.must('CONFIG', 'GET', 'thread-mode', 'net-io',
                                                   'databases', 'read-local'))] * 2))
                    assert shown == {b'thread-mode': mode.encode(), b'net-io': engine.encode(),
                                     b'databases': str(databases).encode(),
                                     b'read-local': b'1' if databases == 16 else b'0'}, shown
            stop, ready = threading.Event(), threading.Barrier(5)
            lock = threading.Lock()

            def write():
                try:
                    with closing(n.connect(a.port)) as c:
                        ready.wait(10)
                        began = time.monotonic()
                        i = 0
                        while i < minimum_writes or time.monotonic() - began < minimum_seconds:
                            i += 1
                            c.must('CONFIG', 'SET', 'latency-tracking-info-percentiles', values[i % 2])
                            result['writes'] = i
                            if time.monotonic() - began > 60:
                                break
                except BaseException as e:
                    with lock:
                        result['errors'].append('writer: ' + type(e).__name__ + ': ' + str(e)[:200])
                finally:
                    stop.set()

            def read():
                try:
                    with closing(n.connect(a.port)) as c:
                        ready.wait(10)
                        while not stop.is_set():
                            raw = c.must('INFO', 'latencystats')
                            labels = None
                            try:
                                text = raw.decode('ascii')
                                rows = dict(line.split(':', 1) for line in text.splitlines() if ':' in line)
                                row = rows.get('latency_percentiles_usec_ping', '')
                                labels = [part.split('=')[0] for part in row.split(',') if part]
                            except UnicodeDecodeError:
                                pass
                            with lock:
                                result['reads'] += 1
                                if labels is None:
                                    result['corrupt'] += 1
                                if labels not in (['p10'] * count, ['p90'] * count):
                                    result['torn'] += 1
                                    if result['first'] is None:
                                        result['first'] = dict(
                                            labels=-1 if labels is None else len(labels),
                                            after_writes=result['writes'], read=result['reads'])
                except BaseException as e:
                    with lock:
                        result['errors'].append('reader: ' + type(e).__name__ + ': ' + str(e)[:200])

            workers = [threading.Thread(target=write)] + [threading.Thread(target=read) for _ in range(4)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(90)
            assert not any(worker.is_alive() for worker in workers), result
            with closing(n.connect(a.port)) as c:
                assert c.must('PING') == b'PONG'
        results.append(result)
    (a.output / f'latency-{mode}-{engine}-observations.json').write_text(json.dumps(results, indent=2))
    # Non-vacuous: every leg completed its writes with concurrent readers.
    assert all(r['writes'] >= minimum_writes and r['reads'] >= 400 and not r['errors'] and
               not r['torn'] and not r['corrupt'] for r in results), results
    return [dict(databases=r['databases'], shards=r['shards'], writes=r['writes'], reads=r['reads'])
            for r in results]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--case', required=True, choices=['file', 'acl', 'latency'])
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.binary, a.oracle = str(Path(a.binary).resolve()), str(Path(a.oracle).resolve())
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for mode, engine in [('redis', 'oracle')] + [(m, e) for m in ('1s', '2s') for e in ('uring', 'epoll')]:
        row = dict(mode=mode, engine=engine)
        try:
            row.update(result=globals()[a.case + '_case'](a, mode, engine), passed=True)
        except Exception:
            row.update(passed=False, error=traceback.format_exc())
        rows.append(row)
        print(json.dumps(row), flush=True)
        (a.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    assert all(row['passed'] for row in rows), 'cfgfix2 witness failed'


if __name__ == '__main__':
    main()
