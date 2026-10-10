#!/usr/bin/env python3
"""Bounded SV4.9/SV4.10 witnesses; owns and stops only the child it starts.

The normal invocation must fail on PRE. --suppress-stale is T7's control and
omits only the selected zero store in the test-only binary. No timing skips.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import subprocess
import time

from _lib import Conn, wait_ready
from _gate_process import info, require, stop_process


@contextlib.contextmanager
def server(args, directory, result):
    directory.mkdir(parents=True, exist_ok=False)
    data = directory / 'data'
    data.mkdir()
    listeners = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{args.port}'], text=True)
    require(not listeners.strip(), f'port already owned: {listeners}')
    argv = ['taskset', '-c', args.cores, str(args.binary.resolve()), '--bind', '127.0.0.1',
            '--port', str(args.port), '--dir', str(data.resolve()), '--thread-mode', args.mode,
            '--shards', '16', '--key-lb', '0', '--client-lb', '0',
            '--flip-auto', '0', '--slowlog-log-slower-than', '-1', '--save', '',
            '--appendonly', 'no', '--enable-debug-command', 'yes']
    if args.mode == '2s':
        argv += ['--ratio', '6:2']
    env = os.environ.copy()
    if args.case == 'counters':
        argv = ['setarch', 'x86_64', '-R', *argv]
        env['TSAN_OPTIONS'] = 'halt_on_error=0:exitcode=66:history_size=7'
    result.update(argv=argv, tsan_options=env.get('TSAN_OPTIONS'),
                  binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest())
    with (directory / 'server.log').open('w') as log:
        child = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
        result['pid'] = child.pid
        ready = None
        try:
            ready = wait_ready('127.0.0.1', args.port, timeout=15, process=child,
                               log_path=directory / 'server.log')
            row = info(ready, 'SERVER')
            require(int(row['process_id']) == child.pid, 'listener identity differs from owned child')
            require(row['thread_mode'] == args.mode, 'wrong thread mode')
            result['geometry'] = {k: v for k, v in row.items()
                                  if k in ('thread_mode', 'io_threads', 'executor_threads', 'shards')}
            ready.close()
            ready = None
            yield
        finally:
            if ready:
                ready.close()
            result['forced_kill'] = stop_process(child)
            result['exit_code'] = child.returncode
            result['listeners_after'] = subprocess.check_output(
                ['ss', '-H', '-ltnp', f'sport = :{args.port}'], text=True)
            require(not result['listeners_after'].strip(), 'owned port did not close')
            require(not result['forced_kill'], 'server required forced cleanup')


def counters(args, result):
    # Exact bounded T6 client from round4-read/PENDING.md, with the port supplied
    # by this gate slot instead of the audit's hard-coded 23400-23499 range.
    c = Conn('127.0.0.1', args.port, timeout=3)
    try:
        for i in range(64):
            require(c.must('SET', 'counter-audit', i) == b'OK', 'SET reply')
            require(c.must('GET', 'counter-audit') == str(i).encode(), 'GET reply')
            time.sleep(.004)
        result['set_get_pairs'] = 64
        deadline = time.monotonic() + 2
        rates = []
        while time.monotonic() < deadline:
            row = info(c, 'STATS')
            rate = int(row['instantaneous_ops_per_sec'])
            rates.append(rate)
            if rate > 0:
                break
            time.sleep(.05)
        result['sampler_rates'] = rates
        require(rates and rates[-1] > 0, 'INFO cron sampling was not witnessed')
        result['commandstats'] = c.must('INFO', 'COMMANDSTATS').decode()
    finally:
        c.close()


def status(c):
    raw = c.must('DEBUG', 'racefix-climon', 'status')
    require(isinstance(raw, list) and len(raw) == 9, f'hook status missing: {raw!r}')
    return dict(zip(('stage', 'armed_value', 'worker', 'park_serial', 'other_arm_serial',
                     'final_serial', 'monitor_clients', 'armed_word', 'native_tid'), raw))


def await_stage(c, wanted):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        row = status(c)
        if row['stage'] == wanted:
            return row
        time.sleep(.002)
    raise AssertionError(f'hook never reached stage {wanted}: {row}')


def marker(monitor, key):
    monitor._read_deadline = time.monotonic() + 1
    try:
        while True:
            frame = monitor.read()
            if isinstance(frame, bytes) and f'"{key}" "value"'.encode() in frame:
                return frame.decode()
    except (TimeoutError, OSError):
        return None
    finally:
        monitor._read_deadline = None


def climon(args, result):
    # Retain two sockets on each of two distinct IO owners before arming. The
    # control socket stays off the parked owner; no connection accept is needed
    # while that owner is paused. Every unsuccessful discovery is fresh state.
    held = []
    control = None
    try:
        groups = {}
        for _ in range(256):
            c = Conn('127.0.0.1', args.port, timeout=2)
            held.append(c)
            worker = c.must('DEBUG', 'IO-THREAD')
            groups.setdefault(worker, []).append(c)
            ready = [tid for tid, peers in groups.items() if len(peers) >= 2]
            if len(ready) >= 2:
                break
        require(len(ready) >= 2, 'two distinct IO owners were not witnessed')
        a, b = ready[:2]
        m, arm = groups[a][:2]
        n, control = groups[b][:2]
        for c in held:
            if c not in (m, arm, n, control):
                c.close()
        result['owners'] = dict(closing=a, opening=b)
        require(m.must('MONITOR') == b'OK', 'initial MONITOR')
        require(int(info(control, 'CLIENTS')['monitor_clients']) == 1, 'initial monitor count')
        require(control.must('SET', 'racefix-before-marker', 'value') == b'OK', 'initial SET')
        result['initial_frame'] = marker(m, 'racefix-before-marker')
        require(result['initial_frame'], 'initial MONITOR feed never fired')
        require(arm.must('DEBUG', 'racefix-climon', 'arm',
                         'suppress' if args.suppress_stale else 'store') == b'OK', 'arm hook')
        m.close()
        parked = await_stage(control, 2)
        result['parked'] = parked
        require(parked['armed_value'] == 0 and parked['worker'] == a,
                'wrong worker/value parked')
        require(n.must('MONITOR') == b'OK', 'replacement MONITOR')
        require(int(info(control, 'CLIENTS')['monitor_clients']) == 1, 'replacement monitor count')
        result['before_release'] = status(control)
        baseline = int(info(control, 'STATS')['monitor_feed_lines'])
        require(control.must('DEBUG', 'racefix-climon', 'release') == b'OK', 'release hook')
        final = await_stage(control, 4 if args.suppress_stale else 3)
        result['after_release'] = final
        require(0 < final['park_serial'] < final['other_arm_serial'] < final['final_serial'],
                'A zero publication did not follow B arming')
        require(final['monitor_clients'] == 1, 'live monitor disappeared')
        # A reply from A proves its entire cold refresh has returned (including
        # any repair after the deliberately stale publication). PING cannot
        # itself refresh the armed word. This fence is identical on PRE/POST.
        require(arm.must('PING') == b'PONG', 'closing owner did not finish its refresh')
        result['settled'] = status(control)
        require(control.must('SET', 'racefix-after-marker', 'value') == b'OK', 'marker SET')
        require(control.must('GET', 'racefix-after-marker') == b'value', 'marker GET')
        result['final_frame'] = marker(n, 'racefix-after-marker')
        result['monitor_lines_before'] = baseline
        result['monitor_lines_after'] = int(info(control, 'STATS')['monitor_feed_lines'])
        require(result['final_frame'], 'live MONITOR received no marker within 1 second')
        require(result['monitor_lines_after'] > baseline, 'monitor feed counter did not advance')
    finally:
        if control:
            try:
                control.must('DEBUG', 'racefix-climon', 'release')
            except (OSError, EOFError):
                pass
        for c in held:
            c.close()


def symbolize(log, binary):
    # GCC's TSan sometimes omits inline locations in the large loop templates.
    # Resolve only those PCs against the exact hashed ELF; keep the raw log too.
    pattern = re.compile(r'\(' + re.escape(binary.name) + r'\+(0x[0-9a-f]+)\)')
    addresses = sorted({m[1] for line in log.splitlines() if '<null>' in line
                        for m in pattern.finditer(line)})
    if not addresses:
        return log
    output = subprocess.check_output(['addr2line', '-afiCe', str(binary), *addresses], text=True)
    resolved, address = {}, None
    for line in output.splitlines():
        if re.fullmatch(r'0x[0-9a-f]+', line):
            address = hex(int(line, 16))
            resolved[address] = []
        elif address is not None:
            resolved[address].append(line)
    lines = []
    for line in log.splitlines():
        lines.append(line)
        match = pattern.search(line) if '<null>' in line else None
        if match:
            lines.extend('    [addr2line] ' + value for value in resolved[match[1]])
    return '\n'.join(lines) + '\n'


def tsan_reports(log):
    log = re.sub(r'\bsrc/[A-Za-z0-9_/.\-]+', lambda m: posixpath.normpath(m[0]), log)
    reports = re.findall(r'WARNING: ThreadSanitizer:.*?(?=\n={8,}|\Z)', log, re.S)
    # Accept a PRE confirmation only when both named sides are in the same
    # report. Other warnings remain explicit diagnostics, never confirmation.
    sites = []
    root = Path(__file__).resolve().parents[1]
    for name in ('src/core/io_loop.h', 'src/core/reorder.cc', 'src/net/wb.h'):
        for line, text in enumerate((root / name).read_text().splitlines(), 1):
            if re.search(r'net_(?:input|output)_bytes(?:\s*\+=|\.store)', text):
                sites.append(re.escape(name) + ':' + str(line) + r'\b')
    writer = r'ThreadCtx::note_command|'+ '|'.join(sites)
    confirmed = [r for r in reports if 'info_stats_tick' in r and re.search(writer, r)]
    family = [r for r in reports if r in confirmed or
              (re.search(writer, r) and 'src/cmd/t_server.cc' in r) or re.search(
        r'ThreadCtx::(?:note_command|total_commands|command_calls|command_rejected_calls|command_failed_calls)', r)]
    return dict(reports=len(reports), cron_writer_pairs=len(confirmed),
                counter_reports=len(family), other_reports=len(reports) - len(family),
                runtime_failure='FATAL: ThreadSanitizer' in log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=('counters', 'climon'))
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--mode', choices=('1s', '2s'), required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suppress-stale', action='store_true')
    args = parser.parse_args()
    result = dict(case=args.case, mode=args.mode, suppress_stale=args.suppress_stale, passed=False)
    started = time.monotonic()
    try:
        with server(args, args.output, result):
            (counters if args.case == 'counters' else climon)(args, result)
        result['passed'] = True
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    if args.case == 'counters' and (args.output / 'server.log').exists():
        log = symbolize((args.output / 'server.log').read_text(), args.binary)
        (args.output / 'symbolized.log').write_text(log)
        result['tsan'] = tsan_reports(log)
        if result['tsan']['counter_reports'] or result['tsan']['runtime_failure']:
            result['passed'] = False
        if result.get('exit_code') not in (0, 66):
            result['passed'] = False
    elif result.get('exit_code') != 0:
        result['passed'] = False
    result['seconds'] = time.monotonic() - started
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
