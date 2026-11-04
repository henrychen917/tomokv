"""Owned, pinned oracle/target boots and exact RESP assertions for datafix1."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

from clientfix import Conn, Error, plain


@contextlib.contextmanager
def boot(binary, port, cores, directory, flags=(), *, locale='C', oracle=False):
    assert not subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{port}']).strip()
    directory.mkdir(parents=True, exist_ok=True)
    argv = ['taskset', '-c', cores, str(Path(binary).resolve()), '--bind', '127.0.0.1',
            '--port', str(port), '--dir', str(directory.resolve()), '--save', '',
            '--appendonly', 'no', '--enable-debug-command', 'yes', *flags]
    # Preserve Redis's environment for the live locale assertion.
    if oracle:
        argv += ['--set-proc-title', 'no']
    env = dict(os.environ, LANG='C', LC_ALL='C')
    with (directory / 'server.log').open('w') as log:
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
    print(json.dumps(dict(start=argv, pid=p.pid)), flush=True)
    try:
        deadline = time.monotonic() + 20
        while True:
            assert p.poll() is None, (directory / 'server.log').read_text()
            try:
                with Conn(port) as c:
                    assert c.cmd('PING') == b'PONG'
                break
            except (OSError, TimeoutError):
                assert time.monotonic() < deadline, 'boot timeout'
                time.sleep(.02)
        # Check the owned, ready server's actual environment, not just the
        # requested Popen arguments. Retain only these two nonsensitive fields.
        actual = dict(item.split(b'=', 1) for item in
                      Path(f'/proc/{p.pid}/environ').read_bytes().split(b'\0') if b'=' in item)
        boot_locale = {name: actual[name.encode()].decode() for name in ('LANG', 'LC_ALL')}
        assert boot_locale == {'LANG': locale, 'LC_ALL': locale}, boot_locale
        print(json.dumps(dict(boot_locale=boot_locale, pid=p.pid)), flush=True)
        with Conn(port) as c:
            c.s.settimeout(15)
            yield c
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        print(json.dumps(dict(stop=p.pid, rc=p.returncode)), flush=True)
        assert p.returncode == 0, (directory / 'server.log').read_text()
        deadline = time.monotonic() + 3
        while subprocess.check_output(['ss', '-H', '-ltn', f'sport = :{port}']).strip():
            assert time.monotonic() < deadline, f'owned port {port} still listening after exit'
            time.sleep(.02)


class Pair:
    def __init__(self, oracle, target, receipt):
        self.oracle, self.target, self.receipt = oracle, target, receipt
        self.failures = []
        self.checks = 0

    def check(self, condition, detail):
        self.checks += 1
        if not condition:
            self.failures.append(plain(detail))
            print('FAIL', plain(detail), flush=True)

    def cmd(self, *args, normalize=lambda x: x):
        r = self.oracle.cmd(*args)
        t = self.target.cmd(*args) if self.target else r
        self.receipt.write(json.dumps(plain(dict(argv=args, oracle=r, target=t))) + '\n')
        self.check(normalize(t) == normalize(r), dict(argv=args, oracle=r, target=t))
        return r, t

    def each(self):
        return [('oracle', self.oracle)] + ([('target', self.target)] if self.target else [])


def main(feature, battery, *, multi=False, flags=()):
    p = argparse.ArgumentParser()
    p.add_argument('--binary', default='build/tomokv')
    p.add_argument('--oracle', default=os.environ.get('GATE_DIFFER_ORACLE_BIN',
                   str(Path(os.environ.get('REDIS74_ROOT', '/home/user/Projects/redis74')) /
                       'src/redis-server')))
    p.add_argument('--port', type=int, default=int(os.environ.get('GATE_PORT', 29800)))
    p.add_argument('--cores', default=os.environ.get('GATE_CORES', '48-55'))
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, default=Path('build/datafix1/proof'))
    p.add_argument('--oracle-only', action='store_true')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    failures = []
    # CD4.6 arms non-C collation with CONFIG, like every other C-locale boot.
    boot_locale = 'C'
    legs = [('oracle', '2s', 0, 0)] if args.oracle_only else [
        (engine, mode, local, atomic)
        for engine in ('epoll', 'uring') for mode, local in (('2s', 0), ('1s', 0), ('1s', 1))
        for atomic in ((0, 1) if multi else (0,))]
    for engine, mode, local, atomic in legs:
        name = f'{engine}-{mode}-rl{local}-a{atomic}'
        directory = args.output / name
        try:
            with boot(args.oracle, args.port + 1, args.cores, directory / 'oracle', flags,
                      locale=boot_locale, oracle=True) as oracle:
                target_flags = ['--shards', '16', '--databases', '1',
                                '--thread-mode', mode, '--read-local', str(local), '--atomic', str(atomic),
                                '--net-io', engine, '--flip-auto', '0', *flags]
                if mode == '2s':
                    target_flags += ['--ratio', args.ratio]
                target_context = contextlib.nullcontext(None) if args.oracle_only else boot(
                    args.binary, args.port, args.cores, directory / 'target', target_flags, locale=boot_locale)
                with target_context as target, (directory / 'replies.jsonl').open('w') as receipt:
                    pair = Pair(oracle, target, receipt)
                    battery(pair)
                    if pair.failures:
                        failures.append(dict(leg=name, failures=pair.failures))
                    print(json.dumps(dict(feature=feature, leg=name, checks=pair.checks,
                                          failures=len(pair.failures))), flush=True)
        except Exception as e:
            failures.append(dict(leg=name, exception=repr(e)))
            print('FAIL', name, repr(e), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(dict(feature=feature, legs=len(legs),
                                                           failures=failures), indent=2,
                                                      default=plain) + '\n')
    raise SystemExit(bool(failures))
