#!/usr/bin/env python3
"""Boot failure witnesses. 'build' is offline; ONLY MAINLINE may use 'run'.

All instrumentation lives in copied sources under build/. Production has no
test hook, environment switch, worker counter or added serving-loop branch.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
ARMS = ('witness', 'bypass-probe', 'bypass-load', 'early-ready', 'omit-fd-close', 'omit-worker-join')
HEADER = r'''
#pragma once
extern "C" void boot_event(const char*, int = -1, int = 0);
extern "C" bool boot_case(const char*);
extern "C" bool boot_control(const char*);
extern "C" void boot_stage(const char*);
extern "C" void boot_activation();
extern "C" bool boot_attach(int);
struct BootWorkerScope {
    int tid;
    explicit BootWorkerScope(int id) : tid(id) { boot_event("worker-enter", tid); }
    ~BootWorkerScope() { boot_event("worker-exit", tid); }
};
'''
WITNESS = r'''
#include "boot_witness.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/stat.h>
#include <unistd.h>
#ifndef BOOT_CONTROL
#define BOOT_CONTROL "witness"
#endif
static std::atomic<int> target{-1};
extern "C" void boot_event(const char* name, int tid, int value) {
    char line[128];
    int n = std::snprintf(line, sizeof(line), "BOOT event=%s tid=%d value=%d\n", name, tid, value);
    if (n < 0 || n >= int(sizeof(line)) || ::write(2, line, n) != n) _exit(93);
}
extern "C" bool boot_case(const char* name) {
    const char* value = std::getenv("TOMO_BOOT_CASE");
    return value && !std::strcmp(name, value);
}
extern "C" bool boot_control(const char* name) {
    return std::getenv("TOMO_BOOT_CASE") && !std::strcmp(name, BOOT_CONTROL);
}
static void pause_for_driver() {
    const char* release = std::getenv("TOMO_BOOT_RELEASE");
    if (!release) _exit(94);
    struct stat st;
    for (unsigned attempt = 0; attempt < 3000; ++attempt) {
        if (::stat(release, &st) == 0) return;
        ::usleep(5000);
    }
    boot_event("unentered-release-timeout");
    _exit(95);
}
extern "C" void boot_stage(const char* phase) {
    boot_event(phase);
    if ((!std::strcmp(phase, "Loaded") && boot_case("stop-loaded")) ||
        (!std::strcmp(phase, "Ready") && boot_case("stop-ready"))) pause_for_driver();
}
extern "C" void boot_activation() {
    boot_event("activation-enter");
    if (boot_case("ready-order")) pause_for_driver();
}
extern "C" bool boot_attach(int fd) {
    if (!boot_case("unix-attach")) return true;
    target.store(fd);
    boot_event("attach-failed", -1, fd);
    return false;
}
extern "C" int __real_close(int);
extern "C" int __wrap_close(int fd) {
    if (fd == target.load()) {
        if (boot_control("omit-fd-close")) { boot_event("fd-close-omitted", -1, fd); return 0; }
        boot_event("fd-close", -1, fd);
    }
    return __real_close(fd);
}
'''


def replace(text, old, new, count=None):
    found = text.count(old)
    assert found and (count is None or found == count), (old, found, count)
    return text.replace(old, new)


def build(arm_root):
    source = arm_root / 'source'
    shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'third_party', source / 'third_party', dirs_exist_ok=True)
    (source / 'boot_witness.h').write_text(HEADER)
    (source / 'boot_witness.cc').write_text(WITNESS)
    # Header changes are confined to the four recompiled runtime units.
    path = source / 'src/core/boot_support.h'
    s = path.read_text()
    s = replace(s, '    const int fd = open_listener',
                '    boot_event("probe-enter", -1, tls);\n    const int fd = open_listener', 1)
    s = replace(s, '    if (fd < 0) return false;',
                '    if (fd < 0) { boot_event("probe-failed", -1, tls); '
                'return boot_control("bypass-probe"); }', 1)
    s = replace(s, '    if (cfg.port) std::fprintf',
                '    boot_event("ready-announcement");\n    if (cfg.port) std::fprintf', 1)
    path.write_text(s)
    path = source / 'src/core/io_loop.h'
    s = path.read_text()
    s = replace(s, '    bool attach_listener(int fd) {',
                '    bool attach_listener(int fd) {\n        if (!boot_attach(fd)) return false;', 1)
    s = replace(s, '    bool activate() {',
                '    bool activate() {\n        boot_activation();', 1)
    path.write_text(s)
    changed = ['src/main.cc', 'src/core/genthread.cc', 'src/core/rl2s.cc', 'src/core/reorder.cc']
    for name in changed:
        path = source / name
        s = path.read_text()
        s = replace(s, '            DatabaseMap::WorkerLifetime database_worker',
                    '            BootWorkerScope boot_worker(tid);\n'
                    '            DatabaseMap::WorkerLifetime database_worker')
        s = re.sub(r'(\s+)(ios\[tid\]\.run\w*\(\);)',
                   r'\1boot_event("accepting-worker", tid);\1\2', s)
        join = 'srv.databases().join_workers(srv, pool);'
        s = replace(s, join, 'if (boot_control("omit-worker-join")) { '
                    'for (auto& worker : pool) worker.detach(); boot_event("join-omitted"); '
                    '} else { ' + join + ' boot_event("joined"); }')
        if name == 'src/main.cc':
            s = replace(s, '        load_cv.wait(lock, [&] {',
                        '        if (!boot_control("bypass-load")) load_cv.wait(lock, [&] {', 1)
            s = replace(s, '    if (!load_ok) {',
                        '    if (!load_ok && !boot_control("bypass-load")) {', 1)
            # Generic split has no Ready rendezvous. This hook exposes that fact;
            # it does not invent one or label worker launch as an acknowledgement.
            s = replace(s, '    print_ready_listeners(cfg, unix_listener.bound());',
                        '    boot_stage("Ready");\n    print_ready_listeners(cfg, unix_listener.bound());', 1)
        else:
            s = replace(s, '    if (!boot.wait_loaded(srv.shutting_down())) {',
                        '    if (!boot_control("bypass-load") && !boot.wait_loaded(srv.shutting_down())) {', 1)
            s = replace(s, '    if (!boot.advance_ready(srv.shutting_down()) ||',
                        '    if (boot_control("early-ready")) print_ready_listeners(cfg, unix_listener.bound());\n'
                        '    if (!boot.advance_ready(srv.shutting_down()) ||', 1)
            s = replace(s, '        !boot.advance_running(srv.shutting_down())) {',
                        '        (boot_stage("Ready"), false) ||\n'
                        '        !boot.advance_running(srv.shutting_down())) {', 1)
        # Main has an additional loading=false in its interrupted-load unwind.
        anchor = '    }\n    srv.set_loading(false);'
        s = replace(s, anchor, '    }\n    boot_stage("Loaded");\n    srv.set_loading(false);', 1)
        path.write_text(s)
    path = source / 'src/snapshot/snapshot.cc'
    s = path.read_text()
    s = replace(s, '                         std::string& error) {\n    for (Shard* shard : owner.shards())',
                '                         std::string& error) {\n'
                '    if (boot_case("load-fail")) { boot_event("owned-load-failed"); '
                'error = "injected owned snapshot decode failure"; return false; }\n'
                '    for (Shard* shard : owner.shards())', 1)
    path.write_text(s)
    changed.append('src/snapshot/snapshot.cc')
    commands = [shlex.split(line) for line in (ROOT / 'build/cleanup-boot/PRE/build.log').read_text().splitlines()
                if line.startswith('g++ ')]
    jobs = []
    objects = {}
    for c in commands:
        if '-c' not in c or c[c.index('-c') + 1] not in changed:
            continue
        original_object = c[-1]
        target = arm_root / original_object.removeprefix('build/')
        target.parent.mkdir(parents=True, exist_ok=True)
        c = c.copy()
        c[c.index('-c') + 1] = str(source / c[c.index('-c') + 1])
        c[-1] = str(target)
        c[1:1] = ['-I' + str(source), '-include', str(source / 'boot_witness.h')]
        objects[original_object] = str(target)
        jobs.append((c, target.with_suffix('.build.log')))
    assert len(jobs) == 10, 'both database variants of five changed units'
    def compile_one(job):
        c, log = job
        with log.open('w') as f:
            f.write(shlex.join(c) + '\n'); f.flush()
            subprocess.run(c, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(compile_one, jobs))
    link, = [c for c in commands if '-c' not in c]
    for control in ARMS:
        directory = arm_root / control
        directory.mkdir(exist_ok=True)
        witness = directory / 'witness.o'
        compile_one((['g++', '-std=c++20', '-O2', '-pthread', '-DBOOT_CONTROL="' + control + '"',
                      '-c', str(source / 'boot_witness.cc'), '-o', str(witness)], directory / 'build.log'))
        command = [objects.get(c, str(ROOT / 'build/cleanup-boot/POST' / c.removeprefix('build/'))
                   if c.startswith('build/') and c.endswith('.o') else c) for c in link]
        command[command.index('-o') + 1] = str(directory / 'tomokv')
        command += [str(witness), '-Wl,--wrap=close']
        with (directory / 'build.log').open('a') as log:
            log.write(shlex.join(command) + '\n'); log.flush()
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    print('Built six live-proof arms; NONE executed')


def events(text, name):
    return re.findall(r'^BOOT event=' + re.escape(name) + r' tid=(-?\d+) value=(-?\d+)$', text, re.M)


def verify(case, text, rc, workers, split_plain):
    # Witness absence is always a failure, including timeout/early parser refusal.
    required = {'load-fail': 'owned-load-failed', 'plain-busy': 'probe-failed',
                'tls-busy': 'probe-failed', 'unix-attach': 'attach-failed',
                'stop-loaded': 'Loaded', 'stop-ready': 'Ready', 'ready-order': 'activation-enter'}
    assert events(text, required[case]), 'intended failure/state never fired: ' + required[case]
    entered = events(text, 'worker-enter')
    exited = events(text, 'worker-exit')
    assert entered and len(entered) == len(set(entered)), 'missing/duplicate worker arrivals'
    assert sorted(entered) == sorted(exited) and events(text, 'joined'), 'all arrivals must exit and be joined'
    expected = 2 if split_plain and case in ('load-fail', 'plain-busy', 'tls-busy', 'stop-loaded') else workers
    assert len(entered) == expected, 'wrong exercised worker geometry'
    if case == 'load-fail':
        assert events(text, 'owned-load-failed'), 'owned persistence load failure never fired'
        assert not events(text, 'probe-enter') and not events(text, 'activation-enter'), 'load barrier bypassed'
    if case in ('plain-busy', 'tls-busy'):
        assert events(text, 'probe-failed') == [('-1', str(int(case == 'tls-busy')))], 'intended occupied probe never failed'
        assert not events(text, 'activation-enter'), 'failed probe reached worker activation'
    if case == 'unix-attach':
        failed = events(text, 'attach-failed')
        assert len(failed) == 1, 'Unix attach failure never fired exactly once'
        assert events(text, 'fd-close') == failed, 'failed Unix attach must close the correct fd exactly once'
    if case in ('stop-loaded', 'stop-ready'):
        assert events(text, 'Loaded' if case == 'stop-loaded' else 'Ready'), 'requested stop phase never entered'
    if case == 'ready-order':
        assert len(events(text, 'activation-enter')) in (6, 8), 'every IO activation must be held'
    assert not events(text, 'accepting-worker'), 'accepting worker crossed failed/stopped boot'
    assert not events(text, 'ready-announcement') and not re.search(r'^listening ', text, re.M), 'early readiness advertisement'
    assert rc == (0 if case.startswith('stop-') or case == 'ready-order' else 1), 'incorrect boot exit status'


def wait_for(process, logfile, predicate, label):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        text = logfile.read_text(errors='replace')
        if predicate(text): return text
        if process.poll() is not None: raise AssertionError(label + ': exited before witness\n' + text[-2000:])
        time.sleep(.01)
    raise AssertionError(label + ': intended state never entered within bounded fresh boot')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def self_test():
    """Oracle controls only; these do not claim any live mechanism has fired."""
    def event(name, tid=-1, value=0):
        return f'BOOT event={name} tid={tid} value={value}\n'
    checks = 0
    for split in (False, True):
        for case in ('load-fail', 'plain-busy', 'tls-busy', 'unix-attach', 'stop-loaded', 'stop-ready', 'ready-order'):
            count = 2 if split and case in ('load-fail', 'plain-busy', 'tls-busy', 'stop-loaded') else 8
            arrival = ''.join(event('worker-enter', i) for i in range(count))
            exits = ''.join(event('worker-exit', i) for i in range(count)) + event('joined')
            witness = {'load-fail': event('owned-load-failed'), 'plain-busy': event('probe-failed'),
                       'tls-busy': event('probe-failed', value=1),
                       'unix-attach': event('attach-failed', value=43) + event('fd-close', value=43),
                       'stop-loaded': event('Loaded'), 'stop-ready': event('Ready'),
                       'ready-order': event('activation-enter') * (6 if split else 8)}[case]
            rc = 0 if case.startswith('stop-') or case == 'ready-order' else 1
            good = arrival + witness + exits
            verify(case, good, rc, 8, split)
            mutations = [
                (arrival + exits, rc, 'intended failure/state never fired'),
                (good.replace(event('joined'), ''), rc, 'all arrivals'),
                (good.replace(event('worker-exit', 0), ''), rc, 'all arrivals'),
                (good + event('accepting-worker', 0), rc, 'accepting worker'),
                (good + event('ready-announcement'), rc, 'early readiness'),
                (good, 1 - rc, 'incorrect boot exit status'),
            ]
            if case == 'load-fail': mutations.append((good + event('probe-enter'), rc, 'load barrier bypassed'))
            if case in ('plain-busy', 'tls-busy'):
                mutations.append((good + event('activation-enter'), rc, 'failed probe reached worker activation'))
            if case == 'unix-attach':
                mutations += [(good.replace(event('fd-close', value=43), ''), rc, 'correct fd exactly once'),
                              (good + event('fd-close', value=43), rc, 'correct fd exactly once'),
                              (good.replace(event('fd-close', value=43), event('fd-close', value=44)), rc, 'correct fd exactly once')]
            for text, status, required in mutations:
                try: verify(case, text, status, 8, split)
                except AssertionError as error: assert required in str(error), (case, required, error)
                else: raise AssertionError('oracle accepted mutation: ' + case + ' / ' + required)
                checks += 1
    print(f'Live-log oracle: 14 synthetic valid traces; {checks} bad/unentered traces rejected (live results pending)')


def run(args):
    # Explicitly invoked by the maintainer. No automatic caller from gate or unit.
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cert, key = out / 'cert.pem', out / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    base = ['taskset', '-c', args.cores, str(args.binary.resolve()), '--bind', '127.0.0.1',
            '--thread-mode', args.mode, '--shards', '16', '--databases', str(args.databases),
            '--read-local', str(args.read_local), '--reorder', str(args.reorder), '--net-io', args.net_io,
            '--flip-auto', '0']
    if args.mode == '2s': base += ['--ratio', '6:2']
    cases = args.cases.split(',')
    results = []
    for case in cases:
        directory = out / case
        directory.mkdir()
        log = directory / 'server.log'
        release = directory / 'release'
        port, tls_port = free_port(), free_port()
        while tls_port == port: tls_port = free_port()
        command = base + ['--port', str(port), '--dir', str(directory)]
        blocker = None
        if case in ('plain-busy', 'tls-busy'):
            blocker = socket.socket()
            blocker.bind(('127.0.0.1', port if case == 'plain-busy' else tls_port))
            blocker.listen()
        if case == 'tls-busy':
            command += ['--tls-port', str(tls_port), '--tls-cert-file', str(cert),
                        '--tls-key-file', str(key), '--tls-auth-clients', 'no']
        if case == 'unix-attach':
            # Relative to the fresh child's cwd, avoiding AF_UNIX's 108-byte
            # path limit even when the artifact directory has a long name.
            command += ['--unixsocket', 'server.sock', '--unixsocketperm', '0600']
        if case == 'load-fail':
            # Produce a real readable snapshot before injecting the owned decode failure.
            with (directory / 'fixture.log').open('w') as f:
                fixture = subprocess.Popen(command, stdout=f, stderr=subprocess.STDOUT, cwd=directory,
                                           env={k: v for k, v in os.environ.items() if not k.startswith('TOMO_BOOT_')})
                try:
                    wait_for(fixture, directory / 'fixture.log', lambda s: 'listening on ' in s, 'snapshot fixture')
                    deadline = time.monotonic() + 10
                    while True:
                        try:
                            with socket.create_connection(('127.0.0.1', port), timeout=1) as sock:
                                sock.sendall(b'*1\r\n$4\r\nSAVE\r\n')
                                assert sock.recv(256) == b'+OK\r\n', 'snapshot fixture SAVE failed'
                            break
                        except ConnectionRefusedError:
                            if time.monotonic() > deadline: raise
                            time.sleep(.01)
                finally:
                    fixture.terminate()
                    fixture.wait(timeout=20)
            assert (directory / 'dump.tomo').exists(), 'actual snapshot fixture missing'
        env = dict(os.environ, TOMO_BOOT_CASE=case, TOMO_BOOT_RELEASE=str(release))
        with log.open('w') as f:
            process = subprocess.Popen(command, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=directory)
            try:
                if case in ('stop-loaded', 'stop-ready', 'ready-order'):
                    phase = 'Loaded' if case == 'stop-loaded' else 'Ready'
                    predicate = (lambda s: len(events(s, 'activation-enter')) == (8 if args.mode == '1s' else 6)) \
                        if case == 'ready-order' else (lambda s: bool(events(s, phase)))
                    wait_for(process, log, predicate, case)
                    process.terminate()
                    release.touch()
                rc = process.wait(timeout=20)
                text = log.read_text(errors='replace')
                verify(case, text, rc, 8, args.mode == '2s' and not args.read_local)
                if case == 'unix-attach': assert not (directory / 'server.sock').exists(), 'Unix pathname leaked'
                results.append(dict(case=case, passed=True))
            except (AssertionError, subprocess.TimeoutExpired) as error:
                results.append(dict(case=case, passed=False, error=str(error)))
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()
                if blocker: blocker.close()
    (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
    return all(row['passed'] for row in results)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    b = sub.add_parser('build')
    b.add_argument('--output', type=Path, default=ROOT / 'build/cleanup-boot/live')
    sub.add_parser('self-test', help='serverless oracle controls only')
    r = sub.add_parser('run', help='MAINLINE ONLY: starts real servers')
    r.add_argument('--binary', required=True, type=Path)
    r.add_argument('--output', required=True, type=Path)
    r.add_argument('--cores', default='0-7')
    r.add_argument('--mode', choices=('1s', '2s'), required=True)
    r.add_argument('--read-local', type=int, choices=(0, 1), required=True)
    r.add_argument('--reorder', type=int, choices=(0, 1), default=0)
    r.add_argument('--databases', type=int, choices=(1, 4), default=1)
    r.add_argument('--net-io', choices=('uring', 'epoll'), default='uring')
    r.add_argument('--cases', default='load-fail,plain-busy,tls-busy,unix-attach,stop-loaded,stop-ready,ready-order')
    args = p.parse_args()
    if args.action == 'build': build(args.output.resolve())
    elif args.action == 'self-test': self_test()
    elif not run(args): raise SystemExit(1)


if __name__ == '__main__':
    main()
