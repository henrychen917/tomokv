#!/usr/bin/env python3
"""Disposable owner-local counters and fixed-request-count mechanism runs.

Only copied sources under build/wave5b are instrumented. No counter enters the
release server. Snapshots bracket the client's READY/GO and DONE/STOP barriers;
per-request numbers are event counts, never throughput measurements.
"""
import argparse
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/wave5b'
DOC = ROOT / 'docs/wave5b'
sys.path.insert(0, str(ROOT / 'tests'))
from _lib import Conn

FIELDS = ['parks', 'parks_pending', 'resumes', 'resumes_pending', 'wakes',
          'visits', 'deferrals', 'sends', 'completions']
HOOK = r'''#pragma once
#include <atomic>
#include <cstdlib>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
namespace wave5b_trace {
struct alignas(128) Row { std::atomic<unsigned long long> n[16]; };
inline Row* rows() {
    static Row* data = [] {
        int fd = ::open(std::getenv("WAVE5B_TRACE"), O_RDWR);
        if (fd < 0) std::abort();
        void* p = mmap(nullptr, 128*128, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
        close(fd);
        if (p == MAP_FAILED) std::abort();
        return static_cast<Row*>(p);
    }();
    return data;
}
inline thread_local Row* current = nullptr;
inline void bind(unsigned id) { current = rows() + id; }
inline void add(unsigned field, unsigned long long amount=1) {
    if (current) {
        auto& n = current->n[field];
        n.store(n.load(std::memory_order_relaxed) + amount, std::memory_order_relaxed);
    }
}
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(args):
    source = BUILD / args.arm / 'source'
    source.mkdir(parents=True, exist_ok=True)
    if args.ref == 'working':
        files = {str(p.relative_to(ROOT)): p.read_bytes()
                 for d in ('src', 'third_party') for p in (ROOT/d).rglob('*') if p.is_file()}
        files['Makefile'] = (ROOT/'Makefile').read_bytes()
    else:
        archive = subprocess.check_output(['git', 'archive', args.ref, 'src', 'third_party', 'Makefile'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            files = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    patches = []
    def patch(name, old, new, count=1):
        text = files[name].decode()
        assert text.count(old) == count, (name, old, text.count(old), count)
        files[name] = text.replace(old, new).encode()
        patches.append(dict(path=name, old=old, new=new, count=count))
    if args.revert:
        name = 'src/core/wb_rule.h'
        patch(name, '            const uint8_t previous_deferrals = c->wb_deferrals();\n', '')
        patch(name, '                work += c->wb_deferrals() != previous_deferrals;\n', '')
        patch(name, '        work += served;\n', '        work += served;\n        if (!loop.pending_serve_.empty()) ++work;\n')
    if args.multiplier is not None:
        patch('src/core/wb_rule.h', '#define TOMO_WB_IDLE_MULTIPLIER 2',
              f'#define TOMO_WB_IDLE_MULTIPLIER {args.multiplier}')
    files['wave5b_trace.h'] = HOOK.encode()
    patch('Makefile', 'CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread',
          'CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread\noverride CXXFLAGS += -include wave5b_trace.h')
    for name, prefix in [('src/core/io_loop.h', ''), ('src/core/reorder.cc', 'r7_')]:
        # Both generated and FIFO bodies are counted; no behavioral changes.
        patch(name, '    IoTenure tenure(sig);', '    IoTenure tenure(sig);\n    wave5b_trace::bind(self_->id());')
        wait = 'wait_ms' if 'const unsigned wait_ms = idle_timeout_ms();' in files[name].decode() else 'Ring::kWaitTimeoutMs'
        ring_wait = '1, wait_ms' if wait == 'wait_ms' else '1'
        for call, count in [(prefix+f'epoll_pass<HasUnix, HasTls, Fused>({wait});', 1),
                            (prefix+f'epoll_pass<HasUnix, HasTls, false>({wait});', 1),
                            (f'ring_.submit_and_wait({ring_wait});', 2)]:
            patch(name, call,
                  'wave5b_trace::add(0); wave5b_trace::add(1, !pending_serve_.empty());\n'
                  '                        '+call+'\n'
                  '                        wave5b_trace::add(2); wave5b_trace::add(3, !pending_serve_.empty());', count)
        n = files[name].decode().count('self_->sig().wakes_recv++;')
        patch(name, 'self_->sig().wakes_recv++;', 'self_->sig().wakes_recv++; wave5b_trace::add(4);', n)
    patch('src/core/wb_rule.h', '            ++visits;', '            ++visits; wave5b_trace::add(5);')
    patch('src/core/wb_rule.h', '                loop.pending_serve_.push_back(c);',
          '                wave5b_trace::add(6);\n                loop.pending_serve_.push_back(c);')
    n = files['src/net/wb.h'].decode().count('stats_.sends_submitted++;')
    patch('src/net/wb.h', 'stats_.sends_submitted++;', 'stats_.sends_submitted++; wave5b_trace::add(7);', n)
    patch('src/core/io_loop.h', '        return n + pubsub_work;',
          '        wave5b_trace::add(8, n);\n        return n + pubsub_work;')
    for name, data in files.items():
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data: path.write_bytes(data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/(args.arm+'-instrumentation.json')).write_text(json.dumps(dict(ref=args.ref, revert=args.revert,
        multiplier=args.multiplier, source=str(source), hook=HOOK, patches=patches), indent=2)+'\n')
    if args.prepare_only:
        print(json.dumps(dict(arm=args.arm, source=str(source), patches=len(patches))), flush=True)
        return
    with (BUILD/(args.arm+'-build.log')).open('w') as log:
        subprocess.run(['taskset','-c',args.build_cores,'make',f'-j{args.jobs}','all'], cwd=source,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = BUILD/('trace-'+args.arm)
    shutil.copy2(source/'build/tomokv', binary)
    print(json.dumps(dict(arm=args.arm, binary=str(binary), sha256=sha(binary))), flush=True)


def snapshot(memory):
    return [list(struct.unpack_from('16Q', memory, t*128)[:len(FIELDS)]) for t in range(6)]


def line(process):
    assert select.select([process.stdout], [], [], 90)[0], 'client barrier timeout'
    value = process.stdout.readline().strip()
    assert value, ('client exited', process.poll())
    return value


def run(args):
    output = args.output_dir/args.name
    output.mkdir(parents=True, exist_ok=True)
    client_bin = BUILD/'client'
    subprocess.run(['taskset','-c',args.load_cores,'g++','-std=c++20','-O2','-pthread',
                    str(ROOT/'tests/wave5b_client.cc'),'-o',str(client_bin)], check=True)
    for repeat in range(args.repeats):
        for command, atomic in [('MGET',1),('MGET',0),('MSET',1)]:
            # Alternate arm order; this is an event-count control, not ABBA throughput.
            arms = args.arms if repeat % 2 == 0 else list(reversed(args.arms))
            for arm in arms:
                binary = BUILD/('trace-'+arm)
                name = f'{repeat}-{command}-a{atomic}-{arm}'
                directory = output/name
                directory.mkdir(exist_ok=True)
                trace = directory/'counters'
                with trace.open('wb') as f: f.truncate(128*128)
                port = args.port
                assert not subprocess.check_output(['ss','-H','-ltn',f'sport = :{port}']).strip()
                cmd = ['taskset','-c',args.server_cores,str(binary),'--port',str(port),'--bind','127.0.0.1',
                       '--shards','16','--ratio','6:2','--thread-mode','2s','--net-io','uring',
                       '--read-local','0','--atomic',str(atomic),'--key-lb','0','--client-lb','0',
                       '--flip-auto','0','--save','','--appendonly','no','--dir',str(directory)]
                server = None; client = None
                try:
                    with (directory/'server.log').open('w') as log, trace.open('r+b') as f:
                        server = subprocess.Popen(cmd, env=dict(os.environ,WAVE5B_TRACE=str(trace)),
                                                  stdout=log, stderr=subprocess.STDOUT)
                        deadline = time.monotonic()+30
                        while True:
                            assert server.poll() is None, ('boot failed', str(directory))
                            try:
                                c=Conn('127.0.0.1',port,timeout=1)
                                assert c.cmd('PING') == b'PONG'; c.close(); break
                            except ConnectionRefusedError:
                                assert time.monotonic()<deadline; time.sleep(.01)
                        with mmap.mmap(f.fileno(),0) as memory:
                            client = subprocess.Popen(['taskset','-c',args.load_cores,str(client_bin),str(port),
                                command,str(args.requests)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
                            assert line(client) == 'READY'
                            before=snapshot(memory)
                            client.stdin.write('GO\n'); client.stdin.flush()
                            assert line(client) == f'DONE {64*args.requests}'
                            after=snapshot(memory)
                            client.stdin.write('STOP\n'); client.stdin.flush()
                            assert client.wait(timeout=10)==0
                        counts = {field: sum(a[i]-b[i] for a,b in zip(after,before)) for i,field in enumerate(FIELDS)}
                        assert all(v >= 0 for v in counts.values()), ('counter moved backward', counts)
                        assert all(counts[k] > 0 for k in ('visits','deferrals','sends','completions')), ('mechanism did not fire', counts)
                        row = dict(arm=arm, command=command, atomic=atomic, repeat=repeat, requests=64*args.requests,
                                   connections=64, depth=8, value_bytes=64, counts=counts,
                                   per_request={k:v/(64*args.requests) for k,v in counts.items()},
                                   before=before, after=after, binary_sha256=sha(binary), argv=cmd,
                                   client_sha256=sha(client_bin), load_cores=args.load_cores)
                        (directory/'result.json').write_text(json.dumps(row,indent=2)+'\n')
                        print(json.dumps({k:v for k,v in row.items() if k not in ('before','after','argv')}),flush=True)
                finally:
                    if client and client.poll() is None: client.kill(); client.wait()
                    if server and server.poll() is None:
                        server.terminate()
                        try: server.wait(timeout=15)
                        except subprocess.TimeoutExpired: server.kill(); server.wait(); raise


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    b=sub.add_parser('prepare'); b.add_argument('arm'); b.add_argument('--ref',default='working'); b.add_argument('--revert',action='store_true')
    b.add_argument('--multiplier', type=int, choices=(2,4,8))
    b.add_argument('--build-cores', default='64-111'); b.add_argument('--jobs', type=int, default=32)
    b.add_argument('--output-dir', type=Path, default=DOC)
    b.add_argument('--prepare-only', action='store_true', help='validate and write the copied source without building')
    r=sub.add_parser('run'); r.add_argument('--arms',nargs='+',required=True); r.add_argument('--name',required=True)
    r.add_argument('--repeats',type=int,default=3); r.add_argument('--requests',type=int,default=2048)
    r.add_argument('--server-cores', default='64-71'); r.add_argument('--load-cores', default='72-111')
    r.add_argument('--port', type=int, default=26890); r.add_argument('--output-dir', type=Path, default=DOC)
    args=p.parse_args(); BUILD.mkdir(parents=True,exist_ok=True)
    (prepare if args.action=='prepare' else run)(args)
