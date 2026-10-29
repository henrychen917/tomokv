#!/usr/bin/env python3
"""Reproduce SNAP-STORM-1 and keep the stuck clients CONNECTED while capturing state.

Boots one server (no gdb), runs an EXEC/script + writer storm with a BGSAVE loop, and on the
first worker whose reply does not arrive within --stuck seconds it stops the BGSAVE loop, leaves
the stuck socket open and records INFO, CLIENT LIST, and optionally a gdb core of the live
process. Then it waits --linger seconds to see whether the stuck reply ever arrives without a
disconnect, records again, and tears down.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, '/home/user/Projects/cx-snapfix/tests')
from _lib import Conn, RespError, encode, wait_ready  # noqa: E402

WRITE = "return {redis.call('INCR',KEYS[1]),redis.call('INCR',KEYS[2])}"


def info(port, section='everything'):
    with contextlib.closing(Conn('127.0.0.1', port, timeout=2)) as c:
        out = {}
        for line in c.must('INFO', section).decode(errors='replace').splitlines():
            k, _, v = line.partition(':')
            if k and not k.startswith('#'):
                out[k] = v
        return out


def client_list(port):
    with contextlib.closing(Conn('127.0.0.1', port, timeout=2)) as c:
        return c.must('CLIENT', 'LIST').decode(errors='replace')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', required=True)
    p.add_argument('--mode', default='1s')
    p.add_argument('--engine', default='uring')
    p.add_argument('--atomic', type=int, default=1)
    p.add_argument('--port', type=int, default=20210)
    p.add_argument('--cores', default='16-23')
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--stuck', type=float, default=3)
    p.add_argument('--linger', type=float, default=5)
    p.add_argument('--mix', default='execs,writers')
    p.add_argument('--core', action='store_true')
    p.add_argument('--gdb', action='store_true')
    p.add_argument('--watchdog', type=float, default=0)
    p.add_argument('--bgsave-interval', type=float, default=0.1)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    flags = ['--bind', '127.0.0.1', '--port', str(args.port), '--dir', str(args.out.resolve()),
             '--save', '', '--appendonly', 'no', '--appendfsync', 'no',
             '--enable-debug-command', 'yes', '--shards', '16', '--thread-mode', args.mode,
             '--net-io', args.engine, '--atomic', str(args.atomic),
             '--read-local', '1' if args.mode == '1s' else '0', '--key-lb', '0', '--client-lb', '0',
             '--flip-auto', '0', '--databases', '16']
    if args.mode == '2s':
        flags += ['--ratio', '6:2']
    argv = ['taskset', '-c', args.cores, str(Path(args.binary).resolve()), *flags]
    if args.gdb:
        core = (args.out / 'stall.core').resolve()
        argv = ['taskset', '-c', args.cores, 'gdb', '-q', '-batch', '-ex', 'set pagination off',
                '-ex', 'handle SIGINT stop nopass', '-ex', 'handle SIGPIPE nostop noprint pass',
                '-ex', 'run', '-ex', 'thread apply all bt', '-ex', f'generate-core-file {core}',
                '-ex', 'kill', '--args', str(Path(args.binary).resolve()), *flags]
    log = (args.out / 'server.log').open('w')
    proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    result = dict(argv=argv, stalled=False)
    try:
        c = wait_ready('127.0.0.1', args.port, process=None if args.gdb else proc, timeout=60)
        c.sock.settimeout(10)
        pid = int(info(args.port, 'server')['process_id'])
        result['pid'] = pid
        first = None
        keys = None
        for i in range(1000):
            key = f'storm:{i}'
            placement = c.must('DEBUG', 'SHARDS', key)[0]
            if first is None:
                first = (key, placement)
            elif placement[1] != first[1][1]:
                keys = [first[0], key]
                result['geometry'] = [first[1], placement]
                break
        result['keys'] = keys
        c.must('MSET', keys[0], 0, keys[1], 0)
        mix = set(args.mix.split(','))
        stop = threading.Event()
        stuck = []
        counts = [0] * 20
        maxlat = [0.0] * 20
        hist = {}
        ids = [None] * 20
        socks = []
        errors = []
        sigint_sent = []
        opstart = [0.0] * 20
        watchdog_fired = []

        def enabled(i):
            return ('scripts' if i < 8 else 'execs' if i < 16 else 'writers') in mix

        def worker(i):
            if not enabled(i):
                return
            client = Conn('127.0.0.1', args.port, timeout=args.stuck)
            socks.append(client)
            try:
                ids[i] = client.must('CLIENT', 'ID')
                while not stop.is_set():
                    t0 = time.monotonic()
                    opstart[i] = t0
                    if i < 8:
                        reply = client.cmd('EVAL', WRITE, 2, *keys)
                        # The base refuses an over-full cross-owner window or an exhausted OCC
                        # retry instead of queueing; a refusal writes nothing and is not a stall.
                        if isinstance(reply, RespError) and str(reply).startswith(
                                ('TRYAGAIN Cross-shard', 'BUSY Cross-shard')):
                            opstart[i] = 0.0
                            continue
                        assert isinstance(reply, list), reply
                    elif i < 16:
                        if i >= 12:
                            client.must('WATCH', *keys)
                        client.raw(encode('MULTI') + encode('INCR', keys[0]) +
                                   encode('INCR', keys[1]) + encode('EXEC'))
                        head = [client.read() for _ in range(3)]
                        assert head == [b'OK', b'QUEUED', b'QUEUED'], head
                        reply = client.read()
                        assert reply is None or isinstance(reply, list), reply
                    else:
                        client.must('INCR', keys[(i - 16) % 2])
                    counts[i] += 1
                    opstart[i] = 0.0
                    lat = time.monotonic() - t0
                    if lat > maxlat[i]:
                        maxlat[i] = lat
                    b = 0 if lat < 0.01 else 1 if lat < 0.1 else 2 if lat < 0.5 else 3 if lat < 1 else 4
                    hist[b] = hist.get(b, 0) + 1
            except (TimeoutError, socket.timeout):
                if args.gdb and not stop.is_set() and not sigint_sent:
                    sigint_sent.append(i)
                    try:
                        ss = subprocess.run(['ss', '-tnio', 'state', 'established',
                                             f'( sport = :{args.port} or dport = :{args.port} )'],
                                            capture_output=True, text=True, timeout=10)
                        (args.out / 'ss-live.txt').write_text(ss.stdout)
                    except Exception:  # noqa: BLE001
                        pass
                    os.kill(result['pid'], signal.SIGINT)
                stuck.append(dict(worker=i, client_id=ids[i], at=time.monotonic()))
                stop.set()
            except Exception as e:  # noqa: BLE001
                errors.append(dict(worker=i, error=repr(e)))
                stop.set()

        def watchdog():
            while not stop.is_set():
                now = time.monotonic()
                for k in range(20):
                    st = opstart[k]
                    if st and now - st > args.watchdog:
                        watchdog_fired.append(dict(worker=k, client_id=ids[k], waited=round(now - st, 3)))
                        try:
                            a0 = info(args.port)
                            time.sleep(0.3)
                            a1 = info(args.port)
                            delta = {}
                            for kk, vv in a1.items():
                                try:
                                    dv = int(vv) - int(a0.get(kk, 0))
                                except ValueError:
                                    continue
                                if dv:
                                    delta[kk] = dv
                            (args.out / 'live-delta.json').write_text(json.dumps(dict(delta=delta, info=a1, still_waiting=[
                                (j, round(time.monotonic() - opstart[j], 3)) for j in range(20) if opstart[j]]), indent=1))
                        except Exception as e:  # noqa: BLE001
                            (args.out / 'live-delta.json').write_text(repr(e))
                        if args.gdb:
                            os.kill(result['pid'], signal.SIGINT)
                            sigint_sent.append(k)
                        try:
                            ss = subprocess.run(['ss', '-tnio', 'state', 'established',
                                                 f'( sport = :{args.port} or dport = :{args.port} )'],
                                                capture_output=True, text=True, timeout=10)
                            (args.out / 'ss-live.txt').write_text(ss.stdout)
                        except Exception:  # noqa: BLE001
                            pass
                        stop.set()
                        return
                time.sleep(0.01)
        if args.watchdog > 0:
            threading.Thread(target=watchdog, daemon=True).start()
        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(20)]
        for t in threads:
            t.start()
        deadline = time.monotonic() + args.seconds
        saves = 0
        while time.monotonic() < deadline and not stop.is_set():
            if args.bgsave_interval <= 0:
                time.sleep(0.1)
                continue
            try:
                reply = c.cmd('BGSAVE')
            except (TimeoutError, socket.timeout):
                result['bgsave_timeout'] = True
                stop.set()
                break
            if reply == b'Background saving started':
                saves += 1
            time.sleep(args.bgsave_interval)
        result['saves'] = saves
        stop.set()
        for t in threads:
            t.join(timeout=args.stuck + 2)
        result['counts'] = counts
        result['maxlat'] = [round(x, 3) for x in maxlat]
        result['hist'] = hist
        result['stuck'] = stuck
        result['watchdog'] = watchdog_fired
        if watchdog_fired:
            stuck.append(dict(watchdog=watchdog_fired))
        result['errors'] = errors
        result['client_ids'] = ids
        if stuck or result.get('bgsave_timeout'):
            result['stalled'] = True
            snap = {}
            try:
                snap['info0'] = info(args.port)
                snap['clients0'] = client_list(args.port)
                time.sleep(1)
                snap['info1'] = info(args.port)
            except Exception as e:  # noqa: BLE001
                snap['info_error'] = repr(e)
            try:
                ss = subprocess.run(['ss', '-tnio', 'state', 'established', f'( sport = :{args.port} or dport = :{args.port} )'],
                                    capture_output=True, text=True, timeout=10)
                (args.out / 'ss.txt').write_text(ss.stdout)
            except Exception as e:  # noqa: BLE001
                snap['ss_error'] = repr(e)
            if args.gdb:
                if not sigint_sent:
                    os.kill(pid, signal.SIGINT)
                try:
                    proc.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    pass
            if args.core:
                core = args.out / 'stall.core'
                g = subprocess.run(['taskset', '-c', '24-31', 'gdb', '-q', '-batch', '-p', str(pid),
                                    '-ex', 'set pagination off', '-ex', 'thread apply all bt',
                                    '-ex', f'generate-core-file {core}', '-ex', 'detach'],
                                   capture_output=True, text=True, timeout=300)
                (args.out / 'stall-bt.txt').write_text(g.stdout + g.stderr)
            # Does the stuck reply arrive without a disconnect?
            time.sleep(args.linger)
            try:
                snap['clients1'] = client_list(args.port)
                snap['info2'] = info(args.port)
            except Exception as e:  # noqa: BLE001
                snap['info_error2'] = repr(e)
            late = []
            for s in stuck:
                cl = socks[[k for k in range(len(socks))][0]] if False else None
            result['late_replies'] = late
            (args.out / 'snapshot.json').write_text(json.dumps(snap, indent=1))
        for s in socks:
            with contextlib.suppress(Exception):
                s.close()
        with contextlib.suppress(Exception):
            c.must('SHUTDOWN', 'NOSAVE')
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        result['rc'] = proc.returncode
        (args.out / 'result.json').write_text(json.dumps(result, indent=1))
        print(json.dumps({k: result.get(k) for k in ('stalled', 'stuck', 'errors', 'saves', 'rc',
                                                     'bgsave_timeout', 'maxlat', 'hist')}), flush=True)


if __name__ == '__main__':
    main()
