"""NT4.19: 10,000 live idle clients return burst input/output memory without client traffic."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import subprocess
import resource
from pathlib import Path
import time
import _netfix as n

CLIENTS = 10000
BURST = b'netfix-burst-' * 10923  # >128 KiB; copied ECHO exercises both input and output.


def policy_unit(a):
    # An active connection must keep its sampled recent peak, not just the inline
    # minimum. This source-level check supplements the binary/RSS matrix below.
    source = r'''
#include <src/net/idle_buffers.h>
#include <cassert>
namespace tomo { void multi_session_destroy(MultiSession* p) { assert(!p); } }
int main() {
    tomo::Client c(-1);
    tomo::IdleBuffers policy;
    auto& b = c.fill_buf();
    b.reserve(65536); b.commit_raw(49152);
    c.set_last_interaction_s(100);
    policy.visit(c, 100000, false, false);
    b.clear();
    policy.visit(c, 105001, false, false); // reset the old burst peak
    c.set_last_interaction_s(106);
    b.commit_raw(4096);
    policy.visit(c, 106000, false, false);
    assert(b.size() == 4096); // pending bytes cannot be reclaimed
    b.clear();
    policy.visit(c, 106001, false, true);
    assert(b.cap() == 65536); // OpenSSL's pinned plaintext is a separate fence
    policy.visit(c, 106002, false, false);
    assert(b.cap() >= 4097 && b.cap() < 65536);
    policy.visit(c, 111003, false, false);
    policy.visit(c, 111004, false, false);
    assert(b.cap() == tomo::kWbufInline);
    size_t avail;
    c.read_space(65536, avail, true);
    assert(policy.visit(c, 112000, true, false));
    assert(c.rcap() >= 65536); // cancellation acknowledgement is not a pointer fence
    assert(!policy.visit(c, 112001, false, false));
    assert(c.rcap() == tomo::kRbufInitial);
}
'''
    binary = a.output / 'policy-unit'
    subprocess.run(['g++', '-std=c++20', '-O2', '-pthread', '-I.', '-x', 'c++', '-',
                    '-o', str(binary)], input=source, text=True, check=True)
    subprocess.run([str(binary)], check=True)
    # Compile a throwaway broken policy: restoring the erroneous inline-only
    # shrink must fail this same test. No production switch or binary is changed.
    control = a.output / 'control/src/net'
    control.mkdir(parents=True, exist_ok=True)
    header = Path('src/net/idle_buffers.h').read_text()
    old = 'std::max(kWbufInline, p.output[i] + 1)'
    assert header.count(old) == 1
    (control / 'idle_buffers.h').write_text(header.replace(old, 'kWbufInline'))
    broken = a.output / 'policy-control'
    subprocess.run(['g++', '-std=c++20', '-O2', '-pthread', '-I'+str(a.output / 'control'),
                    '-Isrc/net', '-I.', '-x', 'c++', '-', '-o', str(broken)],
                   input=source, text=True, check=True)
    result = subprocess.run([str(broken)], capture_output=True, text=True,
                            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
    assert result.returncode != 0 and 'b.cap() >= 4097' in result.stderr, result
    print('PASS policy unit; inline-only shrink control failed at recent-peak assertion', flush=True)


def rss(pid):
    with open(f'/proc/{pid}/status') as f:
        return next(int(line.split()[1]) * 1024 for line in f if line.startswith('VmRSS:'))


def rows(admin):
    return [dict(word.split(b'=', 1) for word in row.split())
            for row in admin.must('CLIENT', 'LIST').splitlines()]


def pinned_streams(port, certs, admin):
    # Keep both a partial multibulk input and a witnessed nonempty output alive
    # across a whole peak-reset window. The cold allocator must preserve both.
    with closing(n.connect(port, certs)) as partial, closing(n.connect(port, certs)) as slow:
        payload = b'partial-frame-' * 16384
        frame = n._lib.encode('ECHO', payload)
        split = len(frame) // 3
        partial.raw(frame[:split])
        slow_id = slow.must('CLIENT', 'ID')
        output = b'pending-output-' * 524288
        slow.raw(n._lib.encode('ECHO', output))
        deadline = time.monotonic() + 5
        while True:
            state = next(r for r in rows(admin) if int(r[b'id']) == slow_id)
            if int(state[b'omem']) > 0:
                break
            assert time.monotonic() < deadline, 'nonempty output window never opened'
            time.sleep(.02)
        time.sleep(7)
        partial.raw(frame[split:])
        assert partial.read() == payload, 'partial frame corrupted by reclamation'
        slow.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        slow.sock.settimeout(30)
        assert slow.read() == output, 'pending reply corrupted by reclamation'
        assert partial.must('PING') == slow.must('PING') == b'PONG'


def test(a, port, certs, proc, oracle):
    clients = []
    samples = []
    try:
        with closing(n.connect(port, certs)) as admin:
            admin_id = admin.must('CLIENT', 'ID')
            def open_client(_):
                c = n.connect(port, certs)
                clients.append(c)
                assert c.must('ECHO', b'w' * 16300) == b'w' * 16300
            with ThreadPoolExecutor(max_workers=32) as workers:
                list(workers.map(open_client, range(CLIENTS)))
            assert len(rows(admin)) == CLIENTS + 1
            # Warm the observer's CLIENT LIST storage before the baseline. No PURGE and no
            # allocator tuning: resident memory is sampled under the shipped policy.
            time.sleep(8)
            baseline = rss(proc.pid)
            peak = baseline
            def echo(c):
                assert c.must('ECHO', BURST) == BURST
            with ThreadPoolExecutor(max_workers=32) as workers:
                for i, _ in enumerate(workers.map(echo, clients)):
                    if i % 250 == 0:
                        peak = max(peak, rss(proc.pid))
            # Witness actual burst allocation before waiting, independently of the RSS check.
            observed = rows(admin)
            grown = sum(int(r.get(b'rbs', b'0')) > 16384 for r in observed)
            if not oracle:
                assert grown > 0, 'no burst-grown input buffer witnessed'
            start = time.monotonic()
            ceiling = baseline + max(32 << 20, baseline // 20)
            while time.monotonic() - start < 30:
                current = rss(proc.pid)
                samples.append([round(time.monotonic() - start, 3), current])
                if time.monotonic() - start >= 8 and current <= ceiling:
                    break
                time.sleep(.25)
            after = rows(admin)
            report = dict(clients=CLIENTS, baseline=baseline, burst_peak=peak,
                          grown=grown, idle_rss=samples[-1][1], ceiling=ceiling, samples=samples)
            # Write the failure evidence before assertions, not just successful samples.
            path = a.output / f'memory-{proc.pid}.json'
            path.write_text(json.dumps(report, indent=2))
            assert len(after) == CLIENTS + 1, 'shedding must not disconnect clients'
            if not oracle:
                retained = [r for r in after if int(r[b'id']) != admin_id and
                            int(r.get(b'rbs', b'0')) > 16384]
                # Only the 10,000 silent clients are subjects; the observer is executing CLIENT LIST.
                assert not retained, f'{len(retained)} clients still retain burst input capacity'
            assert samples[-1][1] <= ceiling, report
            # The clients stayed silent throughout the idle interval; verify that the cancelled
            # receive was rearmed and neither stream direction was damaged on every connection.
            def ping(c):
                assert c.must('PING') == b'PONG'
            with ThreadPoolExecutor(max_workers=32) as workers:
                list(workers.map(ping, clients))
            pinned_streams(port, certs, admin)
            report['partial_input_and_pending_output'] = 'preserved across 7 seconds'
            path.write_text(json.dumps(report, indent=2))
            return report
    finally:
        for c in clients:
            c.close()


if __name__ == '__main__':
    args = n.arguments()
    policy_unit(args)
    n.matrix(args, test)
