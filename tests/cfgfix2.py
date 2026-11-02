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
import re
import resource
import signal
import socket
import struct
import subprocess
import threading
import time
import traceback

import _netfix as n


class Server:
    def __init__(self, a, label, mode, engine, *, config=None, extra=(), directory=None, shards=16,
                 env=None):
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
                                  env=dict(os.environ, LC_ALL='C', **(env or {})),
                                  preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
        self.record['pid'] = self.p.pid

    def ready(self, *, may_refuse=False, timeout=15):
        deadline = time.monotonic() + timeout
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
    # Redis 7.4's own reason for each rejected physical line (None: deferred ACL load error).
    malformed = [
        ('user alice on >secret ~* +@all --requirepass ""', None),
        ('save 3600 1 --requirepass ""', 'Invalid save parameters'),
        ('latency-tracking-info-percentiles 50 --requirepass ""',
         'Invalid latency-tracking-info-percentiles parameters'),
        ('help', 'Bad directive or wrong number of arguments'),
    ]
    results = []
    for i, (line, _) in enumerate(malformed):
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
    for (line, reason), row in zip(malformed, results):
        if reason is None:
            # Redis defers unknown command names until ACL initialization.
            assert '--requirepass' in row['error'] and 'ACL' in row['error'], row
            continue
        # Redis's exact banner, physical line number, line text and reason.
        lines = row['error'].splitlines()
        banner = next(i for i, text in enumerate(lines) if text.startswith('*** FATAL CONFIG FILE ERROR'))
        assert lines[banner + 1:banner + 4] == [
            'Reading the configuration file, at line 3', ">>> '" + line + "'", reason], row
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


def auth_case(a, mode, engine):
    """CC5.7: CONFIG SET requirepass must never open an unauthenticated window.

    With the default user off, authentication is required whatever requirepass
    says. One administrator toggles requirepass between "" and a password while
    connector threads open fresh connections and send GET without AUTH. Every
    reply must be NOAUTH, as on Redis.
    """
    results = []
    toggles_wanted, seconds_wanted, connectors = 2000, 3.0, 6
    for databases in (1, 16):
        label = f'auth-{mode}-{engine}-db{databases}'
        extra = ['--requirepass', 'cc57-boot', '--databases', str(databases)]
        if mode != 'redis' and databases == 16:
            extra += ['--read-local', '1', '--atomic', '1', '--reorder', '1']
        result = dict(databases=databases, toggles=0, connections=0, noauth=0, admitted=0,
                      other=0, first=None, errors=[])
        with Server(a, label, mode, engine, extra=extra):
            with closing(n.connect(a.port)) as admin:
                admin.must('AUTH', 'cc57-boot')
                admin.must('ACL', 'SETUSER', 'cc57-admin', 'on', '>cc57-admin', '~*', '&*', '+@all')
                admin.must('AUTH', 'cc57-admin', 'cc57-admin')
                admin.must('ACL', 'SETUSER', 'default', 'off')
                with closing(n.connect(a.port)) as probe:
                    assert str(probe.cmd('GET', 'cc57-key')).find('NOAUTH') >= 0
                stop, ready = threading.Event(), threading.Barrier(connectors + 1)
                lock = threading.Lock()

                def toggle():
                    try:
                        ready.wait(10)
                        began = time.monotonic()
                        i = 0
                        while i < toggles_wanted or time.monotonic() - began < seconds_wanted:
                            i += 1
                            admin.must('CONFIG', 'SET', 'requirepass', '' if i % 2 else 'cc57-pass')
                            result['toggles'] = i
                            if time.monotonic() - began > 60:
                                break
                    except BaseException as e:
                        with lock:
                            result['errors'].append('toggle: ' + type(e).__name__ + ': ' + str(e)[:200])
                    finally:
                        stop.set()

                def connect():
                    request = b'*2\r\n$3\r\nGET\r\n$8\r\ncc57-key\r\n'
                    try:
                        ready.wait(10)
                        while not stop.is_set():
                            with socket.create_connection(('127.0.0.1', a.port), timeout=5) as sock:
                                # Close with RST: tens of thousands of probes leave no TIME_WAIT.
                                sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
                                sock.sendall(request)
                                reply = b''
                                while not reply.endswith(b'\r\n'):
                                    chunk = sock.recv(256)
                                    if not chunk:
                                        break
                                    reply += chunk
                            with lock:
                                result['connections'] += 1
                                if reply.startswith(b'-NOAUTH'):
                                    result['noauth'] += 1
                                    continue
                                if reply.startswith(b'$') or reply.startswith(b'_'):
                                    result['admitted'] += 1
                                else:
                                    result['other'] += 1
                                if result['first'] is None:
                                    result['first'] = dict(reply=reply[:60].decode('ascii', 'replace'),
                                                           after_toggles=result['toggles'])
                    except BaseException as e:
                        with lock:
                            result['errors'].append('connect: ' + type(e).__name__ + ': ' + str(e)[:200])

                workers = [threading.Thread(target=toggle)] + [
                    threading.Thread(target=connect) for _ in range(connectors)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(90)
                assert not any(worker.is_alive() for worker in workers), result
                admin.must('CONFIG', 'SET', 'requirepass', 'cc57-pass')
                with closing(n.connect(a.port)) as probe:
                    assert str(probe.cmd('GET', 'cc57-key')).find('NOAUTH') >= 0
        results.append(result)
    (a.output / f'auth-{mode}-{engine}-observations.json').write_text(json.dumps(results, indent=2))
    assert all(r['toggles'] >= toggles_wanted and r['connections'] >= 1000 and not r['errors'] and
               r['noauth'] == r['connections'] for r in results), results
    return [dict(databases=r['databases'], toggles=r['toggles'], connections=r['connections'])
            for r in results]


def long_command(mode):
    # Each server's own multi-second single-key command: TomoKV executes a large
    # SUNIONSTORE slowly, Redis a large SORT ... STORE. Duration is calibrated.
    if mode == 'redis':
        return 6000000, lambda dst: ('SORT', '{cc6}src', 'STORE', dst)
    return 300000, lambda dst: ('SUNIONSTORE', dst, '{cc6}src')


def populate(c, members):
    batch = 20000
    for first in range(0, members, batch):
        c.must('SADD', '{cc6}src', *range(first, min(members, first + batch)))
    assert c.must('SCARD', '{cc6}src') == members


def sigterm_during(child, c, command, settle=0.3):
    """Send COMMAND without waiting, SIGTERM once it runs, and time the exit."""
    c.send(*command)
    time.sleep(settle)
    signalled = time.monotonic()
    child.p.send_signal(signal.SIGTERM)
    try:
        child.p.wait(180)
    except subprocess.TimeoutExpired:
        child.record['forced_kill'] = True
        child.p.kill()
        child.p.wait(10)
    waited = time.monotonic() - signalled
    try:
        reply = c.read()
        reply = 'error' if isinstance(reply, Exception) else 'reply'
    except (OSError, EOFError):
        reply = 'closed'
    return child.p.returncode, waited, reply


def shutdown_case(a, mode, engine):
    """SIGTERM while one long command runs: delay shutdown, never abort.

    Databases 16 (the default runtime) without a save clause. The command's
    duration is calibrated to exceed PRE's 2.7 s worker-shutdown bound. The
    AOF everysec leg adds a write burst; every acknowledged key must survive.
    """
    members, make = long_command(mode)
    result = dict(members=None, calibrated_seconds=None)
    # Leg 1: no persistence. Calibrate first, so the trial provably overlaps.
    directory = a.output / f'shutdown-{mode}-{engine}-none'
    child = Server(a, directory.name, mode, engine, extra=['--databases', '16'])
    try:
        child.ready()
        with closing(n.connect(a.port)) as c:
            c.sock.settimeout(180)
            for _ in range(4):
                populate(c, members)
                began = time.monotonic()
                c.must(*make('{cc6}calibrate'))
                duration = time.monotonic() - began
                if duration >= 3.5:
                    break
                c.must('DEL', '{cc6}calibrate', '{cc6}src')
                members *= 2
            assert duration >= 3.5, ('long command too short', members, duration)
            result.update(members=members, calibrated_seconds=round(duration, 2))
            rc, waited, reply = sigterm_during(child, c, make('{cc6}trial'))
    finally:
        child.close()
    log = child.logpath.read_text(errors='replace')
    result['none'] = dict(exit_code=rc, waited_seconds=round(waited, 2), long_reply=reply,
                          watchdog='worker shutdown timeout' in log)
    # Leg 2: AOF everysec, write burst, long command, SIGTERM, restart.
    directory = a.output / f'shutdown-{mode}-{engine}-aof'
    extra = ['--databases', '16', '--appendonly', 'yes', '--appendfsync', 'everysec']
    child = Server(a, directory.name, mode, engine, extra=extra, directory=directory)
    acknowledged, tail = [], []
    try:
        child.ready()
        with closing(n.connect(a.port)) as c:
            c.sock.settimeout(180)
            populate(c, members)
            for first in range(0, 20000, 1000):
                keys = [f'cc6-burst:{i}' for i in range(first, first + 1000)]
                for key in keys:
                    c.send('SET', key, key + '-value')
                for key in keys:
                    if c.read() == b'OK':
                        acknowledged.append(key)
            # A second client keeps writing until the server stops answering, so the
            # final acknowledged writes sit inside the last everysec window at shutdown.
            started = threading.Event()

            def trickle():
                try:
                    with closing(n.connect(a.port)) as w:
                        w.sock.settimeout(180)
                        for i in range(10 ** 9):
                            keys = [f'cc6-tail:{i}:{j}' for j in range(20)]
                            for key in keys:
                                w.send('SET', key, key + '-value')
                            for key in keys:
                                if w.read() == b'OK':
                                    tail.append(key)
                            started.set()
                except (OSError, EOFError):
                    pass
                finally:
                    started.set()

            writer = threading.Thread(target=trickle)
            writer.start()
            started.wait(30)
            rc, waited, reply = sigterm_during(child, c, make('{cc6}trial'))
            writer.join(60)
            assert not writer.is_alive()
            acknowledged += tail
    finally:
        child.close()
    log = child.logpath.read_text(errors='replace')
    aof = dict(exit_code=rc, waited_seconds=round(waited, 2), long_reply=reply,
               watchdog='worker shutdown timeout' in log, acknowledged=len(acknowledged),
               tail_acknowledged=len(tail))
    restart = Server(a, directory.name + '-restart', mode, engine, extra=extra, directory=directory)
    try:
        restart.ready(timeout=180)  # replays the populated set before listening
        with closing(n.connect(a.port)) as c:
            c.sock.settimeout(180)
            deadline = time.monotonic() + 120
            while True:
                reply = c.cmd('PING')
                if reply == b'PONG' or time.monotonic() > deadline:
                    break
                time.sleep(0.1)
            missing = 0
            for first in range(0, len(acknowledged), 1000):
                keys = acknowledged[first:first + 1000]
                values = c.must('MGET', *keys)
                missing += sum(value != (key + '-value').encode() for key, value in zip(keys, values))
            aof.update(missing=missing, source_members=c.must('SCARD', '{cc6}src'),
                       trial_exists=c.must('EXISTS', '{cc6}trial'))
    finally:
        restart.close()
    result['aof'] = aof
    (a.output / f'shutdown-{mode}-{engine}-observations.json').write_text(json.dumps(result, indent=2))
    floor = result['calibrated_seconds'] - 0.3 - 1.0
    for leg in (result['none'], aof):
        assert leg['exit_code'] == 0 and not leg['watchdog'], result
        assert leg['waited_seconds'] >= floor, ('shutdown did not wait for the command', result)
    assert aof['acknowledged'] >= 20000 + 20 and aof['missing'] == 0, result
    assert aof['source_members'] == members, result
    if aof['long_reply'] == 'reply':
        assert aof['trial_exists'] == 1, result
    return dict(members=members, calibrated_seconds=result['calibrated_seconds'],
                waited=[result['none']['waited_seconds'], aof['waited_seconds']],
                acknowledged=aof['acknowledged'])


def cpu_list(text):
    cpus = []
    for part in text.split(','):
        first, _, last = part.partition('-')
        cpus += list(range(int(first), int(last or first) + 1))
    return cpus


def clock_ranges(binary):
    """Load-relative ranges of the functions that allocate ObjectIdleClock nodes."""
    out = subprocess.run(['nm', '-C', '--defined-only', '-S', binary], check=True,
                         capture_output=True, text=True).stdout
    ranges = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        address, size, _, name = parts
        if name.endswith('FlatStore::configure_object_idle(bool)') or 'ObjectIdleClock::install(' in name:
            first = int(address, 16)
            ranges.append(f'{first:x}-{first + int(size, 16):x}')
    assert ranges, 'no ObjectIdleClock construction sites found'
    return ','.join(sorted(set(ranges)))


def maxmemory_case(a, mode, engine):
    """SO5.1: a failed idle-clock allocation refuses CONFIG SET maxmemory 0 -> N.

    TomoKV legs preload tests/cfgfix2_alloc_fail.cc, which fails one clock allocation
    on one owner after every owner has started building its clock. The CONFIG SET must
    fail with an apply error, every allocated node must be freed, maxmemory must stay 0
    and the server must keep serving; disarmed, the same CONFIG SET then succeeds. PRE
    either aborts on std::bad_alloc or answers ERR out of memory with the new value already
    published. The oracle has no per-key allocation to fail.
    """
    hook = a.output / 'cfgfix2_alloc_fail.so'
    if mode != 'redis' and not hook.exists():
        subprocess.run(['g++', '-std=c++20', '-O2', '-shared', '-fPIC', '-o', str(hook),
                        str(Path(__file__).with_name('cfgfix2_alloc_fail.cc'))], check=True)
    cpus = cpu_list(a.cores)
    owners = int(a.ratio.split(':')[1]) if mode == '2s' else len(cpus)
    target = cpus[-1]
    keys = 60000
    results = []
    for databases in (1, 16):
        label = f'maxmemory-{mode}-{engine}-db{databases}'
        extra = ['--databases', str(databases)]
        if mode != 'redis' and databases == 16:
            extra += ['--read-local', '1', '--atomic', '1', '--reorder', '1']
        directory = a.output / label
        directory.mkdir(parents=True, exist_ok=True)
        marker, receipt = directory / 'armed', directory / 'allocations.txt'
        marker.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)
        env = None
        if mode != 'redis':
            env = dict(LD_PRELOAD=str(hook), CFGFIX2_FAIL_ARM=str(marker),
                       CFGFIX2_FAIL_RECEIPT=str(receipt), CFGFIX2_FAIL_RANGES=clock_ranges(a.binary),
                       CFGFIX2_FAIL_CPU=str(target), CFGFIX2_FAIL_OWNERS=str(owners))
        result = dict(databases=databases, owners=None if mode == 'redis' else owners,
                      target_cpu=None if mode == 'redis' else target)
        with Server(a, label, mode, engine, extra=extra, directory=directory, env=env) as child:
            if mode != 'redis':
                layout = re.findall(r'thread t\d+: role=\S+ cpu=(\d+) .*?shards=(\d+)',
                                    child.logpath.read_text())
                owning = sorted(int(cpu) for cpu, shards in layout if int(shards))
                assert len(owning) == owners and target in owning, ('owner geometry', layout)
            with closing(n.connect(a.port)) as c:
                c.sock.settimeout(120)
                for first in range(0, keys, 1000):
                    pairs = []
                    for i in range(first, first + 1000):
                        pairs += [f'so51:{i}', f'v{i}']
                    c.must('MSET', *pairs)
                assert c.must('DBSIZE') == keys
                if mode == 'redis':
                    result['set'] = repr(c.cmd('CONFIG', 'SET', 'maxmemory', '100mb'))
                    result['get'] = repr(c.must('CONFIG', 'GET', 'maxmemory'))
                    assert c.must('CONFIG', 'SET', 'maxmemory', '0') == b'OK'
                    results.append(result)
                    continue
                marker.write_text('armed\n')
                try:
                    reply = c.cmd('CONFIG', 'SET', 'maxmemory', '100mb')
                except (OSError, EOFError) as error:
                    reply = error
                finally:
                    marker.unlink(missing_ok=True)
                result['refused'] = repr(reply)
                try:  # Retained for PRE: an OOM reply can coexist with a published value.
                    result['after_get'] = repr(c.cmd('CONFIG', 'GET', 'maxmemory'))
                except (OSError, EOFError) as error:
                    result['after_get'] = type(error).__name__
                assert getattr(reply, 'message', None) == (
                    b"ERR CONFIG SET failed (possibly related to argument 'maxmemory') - "
                    b"Out of memory building the object idle clock. Check server logs."), result
                # Every allocated clock node is freed; read-local retirement may defer it.
                deadline = time.monotonic() + 20
                while True:
                    events = [line.split() for line in receipt.read_text().splitlines()]
                    allocated = {e[1] for e in events if e[0] == '+'}
                    freed = {e[1] for e in events if e[0] == '-'}
                    if allocated <= freed or time.monotonic() > deadline:
                        break
                    c.must('PING')
                    time.sleep(0.05)
                result.update(failures=sum(e[0] == 'F' for e in events), allocated=len(allocated),
                              freed=len(allocated & freed),
                              owner_cpus=len({e[2] for e in events if e[0] == '+'}))
                assert result['failures'] == 1 and allocated <= freed, result
                assert result['owner_cpus'] >= owners, result
                assert c.must('PING') == b'PONG'
                assert c.must('CONFIG', 'GET', 'maxmemory') == [b'maxmemory', b'0'], result
                assert c.must('DBSIZE') == keys and c.must('GET', 'so51:7') == b'v7'
                # Disarmed, the same change succeeds and builds every clock.
                assert c.must('CONFIG', 'SET', 'maxmemory', '100mb') == b'OK'
                assert c.must('CONFIG', 'GET', 'maxmemory') == [b'maxmemory', b'104857600']
                assert isinstance(c.must('OBJECT', 'IDLETIME', 'so51:7'), int)
                assert c.must('CONFIG', 'SET', 'maxmemory', '0') == b'OK'
        results.append(result)
    (a.output / f'maxmemory-{mode}-{engine}-observations.json').write_text(json.dumps(results, indent=2))
    if mode == 'redis':
        assert all(r['set'] == "b'OK'" for r in results), results
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--case', required=True,
                   choices=['file', 'acl', 'latency', 'auth', 'shutdown', 'maxmemory'])
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
