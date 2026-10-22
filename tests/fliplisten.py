#!/usr/bin/env python3
"""FLIP arrival conservation through the gate's owned process/port allocation.

Hold only the coordinator, in the production binary, after every IoPrepare ACK
and before ExDrain. Other workers and both kernel listener engines keep running.
This reaches prepared EX->IO listeners, unlike a BLPOP-held IoDrain. No server
hook, modified binary, or substitute gate runner is used. Each row runs all four
engine/atomic legs, even when an earlier leg fails on the frozen PRE control.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import time
import traceback

from _lib import Conn, RespError, info, wait_ready
from tls import context, generate


def from_socket(sock):
    peer = Conn.__new__(Conn)
    peer.sock = sock
    peer.file = sock.makefile('rb', buffering=4096)
    peer._read_deadline = None
    return peer


def listeners(port):
    result = {}
    for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
        fields = line.split()
        if fields[3] == '0A' and int(fields[1].split(':')[1], 16) == port:
            result[fields[9]] = int(fields[4].split(':')[1], 16)
    return result


def await_file(path, process, timeout=15):
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert process.poll() is None, 'debugger exited before the witnessed window'
        assert time.monotonic() < deadline, 'FLIP never opened the required window'
        time.sleep(.005)


def leg(args, engine, atomic):
    out = args.output / f'{engine}-a{atomic}'
    out.mkdir(parents=True, exist_ok=False)
    # sockaddr_un is only 108 bytes; the gate's artifact path is longer.
    unix_path = Path.cwd() / 'build' / f'fliplisten-{args.port}.sock'
    hit, release = out / 'held.json', out / 'release'
    script = out / 'hold.gdb'
    script.write_text('\n'.join([
        'set pagination off', 'set confirm off', 'set non-stop on',
        'set breakpoint pending on', 'handle SIGPIPE nostop noprint pass',
        'handle SIGTERM nostop noprint pass', 'handle SIGINT nostop noprint pass',
        'python', 'import os, time, json',
        'class Hold(gdb.Breakpoint):',
        '    def stop(self):',
        "        if not str(gdb.parse_and_eval('stage')).endswith('ExDrain'): return False",
        '        self.enabled = False',
        f'        with open({str(hit)!r}, "w") as f:',
        "            json.dump(dict(pid=gdb.selected_inferior().pid, stage=str(gdb.parse_and_eval('stage'))), f)",
        '        deadline = time.monotonic() + 15',
        f'        while not os.path.exists({str(release)!r}) and time.monotonic() < deadline:',
        '            time.sleep(.005)',
        *( ["        gdb.execute('set var this->srv_->flip_deadline_ns_._M_i = 1')"]
           if args.outcome == 'rollback' else []),
        '        return False',
        "Hold('tomo::IoLoop::flip_publish_stage')",
        "Hold('tomo_db0::IoLoop::flip_publish_stage')",
        'end', 'run']) + '\n')
    initial, target = (6, 4) if args.direction == 'io-ex' else (4, 6)
    argv = ['taskset', '-c', args.cores, 'gdb', '-nx', '-q', '-x', str(script), '--args',
            str(args.binary.resolve()), '--bind', '127.0.0.1', '--port', str(args.port),
            '--dir', str(out), '--save', '', '--appendonly', 'no', '--thread-mode', '2s',
            '--ratio', f'{initial}:{8-initial}', '--shards', '16', '--databases', '1',
            '--atomic', str(atomic), '--net-io', engine, '--key-lb', '0', '--client-lb', '0',
            '--flip-auto', '0', '--enable-debug-command', 'yes',
            '--unixsocket', str(unix_path), '--tls-port', str(args.port + 1),
            '--tls-cert-file', str(args.output / 'certs/server.crt'),
            '--tls-key-file', str(args.output / 'certs/server.key'),
            '--tls-ca-cert-file', str(args.output / 'certs/ca.crt')]
    (out / 'command.json').write_text(json.dumps(argv, indent=2) + '\n')
    deadline = time.monotonic() + 10
    while listeners(args.port):
        assert time.monotonic() < deadline, 'allocated gate port is already in use'
        time.sleep(.05)
    peers, clients, tls_peers = [], [], []
    result = dict(engine=engine, atomic=atomic, direction=args.direction, outcome=args.outcome)
    pid = None
    with (out / 'server.log').open('w') as log:
        debugger = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
        try:
            admin = wait_ready('127.0.0.1', args.port, timeout=30)
            admin.sock.settimeout(8)
            issuer = Conn('127.0.0.1', args.port, timeout=8)
            clients += [admin, issuer]
            admin.must('SET', 'fliplisten:once', 0)
            before = int(info(admin, 'stats')['total_connections_received'])
            old = listeners(args.port)
            old_tls = listeners(args.port + 1)
            issuer.send('FLIP', target, 8-target)
            await_file(hit, debugger)
            witness = json.loads(hit.read_text())
            pid = witness['pid']
            assert Path(f'/proc/{pid}/exe').resolve() == args.binary.resolve()
            during = listeners(args.port)
            # New EX->IO sockets really exist before arrivals; IO->EX retains
            # the original listeners until the scheduled completion/rollback.
            assert len(during) >= initial
            if args.direction == 'ex-io':
                assert len(during.keys() - old.keys()) == target-initial, (old, during)
            # Bounded arming: cover every kernel queue on epoll. If a fresh
            # cohort does not open that window, FAIL; never skip the assertion.
            for _ in range(256):
                peer = Conn('127.0.0.1', args.port, timeout=8)
                peers.append(peer)
                peer.send('PING')
                if len(peers) >= 24 and (engine == 'uring' or all(listeners(args.port).values())):
                    break
            queued = listeners(args.port)
            if engine == 'epoll':
                assert set(queued) == set(during) and all(queued.values()), queued
            # A pending TLS handshake retains the listener's TLS identity. Send
            # ClientHello now (TCP_DEFER_ACCEPT), finish only after the FLIP.
            tls_context = context(str(args.output / 'certs'), client='good')
            for _ in range(256):
                raw = socket.create_connection(('127.0.0.1', args.port + 1), timeout=8)
                sock = tls_context.wrap_socket(raw, server_hostname='localhost',
                                               do_handshake_on_connect=False)
                sock.setblocking(False)
                try: sock.do_handshake()
                except ssl.SSLWantReadError: pass
                peer = from_socket(sock)
                peers.append(peer)
                tls_peers.append(peer)
                if len(tls_peers) >= 24 and (engine == 'uring' or all(listeners(args.port + 1).values())):
                    break
            tls_queued = listeners(args.port + 1)
            if engine == 'epoll':
                assert len(tls_queued) >= initial and all(tls_queued.values()), tls_queued
            for _ in range(8):
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(8)
                sock.connect(str(unix_path))
                peer = from_socket(sock)
                peers.append(peer)
                peer.send('PING')
            admin.send('PING')
            released_at = time.monotonic()
            release.touch()
            flip_reply = issuer.read()
            quiesce_end = time.monotonic()
            if args.outcome == 'complete':
                assert flip_reply == b'OK', repr(flip_reply)
            else:
                assert isinstance(flip_reply, RespError) and b'timed out' in flip_reply.message, repr(flip_reply)
            assert admin.read() == b'PONG'
            established_delay = time.monotonic() - quiesce_end
            assert established_delay < 1, ('established connection stalled after FLIP', established_delay)
            served, ids, counters, errors = 0, [], [], []
            for i, peer in enumerate(peers):
                try:
                    if peer in tls_peers:
                        peer.sock.settimeout(8)
                        peer.sock.do_handshake()
                        peer.send('PING')
                    assert peer.read() == b'PONG'
                    peer.send('CLIENT', 'ID')
                    peer.send('INCR', 'fliplisten:once')
                    peer.send('ECHO', f'arrival-{i}')
                    ids.append(peer.read())
                    counters.append(peer.read())
                    assert peer.read() == f'arrival-{i}'.encode()
                    served += 1
                except (OSError, EOFError, AssertionError) as error:
                    errors.append(f'{i}: {type(error).__name__}: {error}')
            after = int(info(admin, 'stats')['total_connections_received'])
            result.update(arrived=len(peers), served=served, errors=errors,
                          accepted_delta=after-before, listeners_before=old,
                          listeners_during=queued, witness=witness,
                          tls_listeners_before=old_tls, tls_listeners_during=tls_queued,
                          tls_arrived=len(tls_peers), unix_arrived=8,
                          remaining_quiesce_s=quiesce_end-released_at,
                          established_after_flip_s=established_delay,
                          unique_ids=len(set(ids)), executions=admin.must('GET', 'fliplisten:once').decode())
            assert served == len(peers), result
            assert len(set(ids)) == len(peers), result
            assert sorted(counters) == list(range(1, len(peers)+1)), result
            assert after-before == len(peers), result
            assert result['remaining_quiesce_s'] < 6.5, result
            assert result['executions'] == str(len(peers)), result
            for peer in peers:
                peer.sock.setblocking(False)
                try:
                    extra = peer.sock.recv(1) if peer in tls_peers else peer.sock.recv(1, socket.MSG_PEEK)
                    assert not extra, ('duplicate/unsolicited reply', extra)
                except (BlockingIOError, ssl.SSLWantReadError):
                    pass
            result['passed'] = True
        finally:
            release.touch()
            for client in peers + clients:
                client.close()
            # Own only this debugger's inferior, even on a failed arming leg.
            if pid is None:
                children = Path(f'/proc/{debugger.pid}/task/{debugger.pid}/children')
                if children.exists():
                    for child in children.read_text().split():
                        try:
                            if Path(f'/proc/{child}/exe').resolve() == args.binary.resolve(): pid = int(child)
                        except FileNotFoundError:
                            pass
            if pid is not None:
                try: os.kill(pid, signal.SIGTERM)
                except ProcessLookupError: pass
                deadline = time.monotonic() + 8
                while Path(f'/proc/{pid}').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
            if debugger.poll() is None:
                try:
                    debugger.stdin.write(b'interrupt -a\nkill inferiors 1\nquit\n')
                    debugger.stdin.close()
                    debugger.wait(timeout=10)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    debugger.kill(); debugger.wait()
            (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    text = (out / 'server.log').read_text(errors='replace')
    assert 'SIGABRT' not in text and 'SIGSEGV' not in text, text[-5000:]
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--direction', choices=('io-ex', 'ex-io'), required=True)
    parser.add_argument('--outcome', choices=('complete', 'rollback'), required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    generate(str(args.output / 'certs'))
    failures = []
    for engine in ('uring', 'epoll'):
        for atomic in (0, 1):
            try: leg(args, engine, atomic)
            except Exception:
                failures.append(f'{engine}-a{atomic}')
                traceback.print_exc()
    print(json.dumps(dict(failed=failures, legs=4)), flush=True)
    raise SystemExit(bool(failures))


if __name__ == '__main__': main()
