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
import time
import traceback

import _netfix as n


class Server:
    def __init__(self, a, label, mode, engine, *, config=None, extra=(), directory=None):
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
            cmd += ['--thread-mode', mode, '--shards', '16', '--net-io', engine]
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--case', required=True, choices=['file'])
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
