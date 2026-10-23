"""Attributed C++ allocation and RSS snapshots, never a throughput workload."""
import contextlib
import os
from pathlib import Path
import re
import subprocess


class Trace:
    def __init__(self, run, label):
        self.run = run
        self.path = run.path / (label + '-allocations.txt')
        self.snapshots = {}

    def __enter__(self):
        self.saved = {key: os.environ.get(key) for key in ['LD_PRELOAD', 'TOMO_ALLOC_TRACE', 'TOMO_ALLOC_BINARY']}
        if not self.run.oracle:
            root = Path(__file__).resolve().parents[1]
            shim = root / 'build/serverfix/alloc-trace.so'
            source = root / 'tests/serverfix_alloc.cc'
            if not shim.exists() or shim.stat().st_mtime < source.stat().st_mtime:
                shim.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(['g++', '-std=c++20', '-O2', '-fPIC', '-shared', str(source),
                                '-o', str(shim), '-ldl'], check=True)
            os.environ.update(LD_PRELOAD=str(shim), TOMO_ALLOC_TRACE=str(self.path),
                              TOMO_ALLOC_BINARY=str(self.run.binary))
        return self

    def snapshot(self, name, pid):
        if self.run.oracle:
            return
        status = Path(f'/proc/{pid}/smaps_rollup').read_text()
        self.snapshots[name] = dict(rss_kib=int(re.search(r'^Rss:\s+(\d+)', status, re.M)[1]))
        with self.path.open('a') as output:
            output.write('MARK ' + name + '\n')

    def __exit__(self, *_):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def verify(self, feature):
        if self.run.oracle:
            return
        lines = self.path.read_text().splitlines()
        addresses = sorted({address for line in lines if line.startswith('N ') for address in line.split()[3:]})
        decoded = subprocess.check_output(['addr2line', '-a', '-f', '-C', '-i', '-e', str(self.run.binary)],
                                         input='\n'.join('0x' + a for a in addresses), text=True)
        symbols = {}
        current = None
        for line in decoded.splitlines():
            if re.fullmatch(r'0x[0-9a-f]+', line):
                current = format(int(line, 16), 'x')
                symbols[current] = ''
            elif current:
                symbols[current] += line + '\n'
        pattern = re.compile('Slowlog|slowlog|ClientDirectoryShard' if feature == 'slowlog' else
                             'AclLog(Store|Entry)|(?:^|\n)tomo(?:_db0)?::acl_(?:log_|set_log_max_len)')
        live = {}
        allocations = []
        for line in lines:
            parts = line.split()
            if parts[0] == 'N':
                stack = ''.join(symbols.get(a, '') for a in parts[3:])
                if pattern.search(stack):
                    entry = dict(size=int(parts[2]), stack=stack)
                    live[parts[1]] = entry
                    allocations.append(entry)
            elif parts[0] == 'D':
                live.pop(parts[1], None)
            elif parts[0] == 'MARK':
                self.snapshots[parts[1]].update(feature_live_bytes=sum(x['size'] for x in live.values()),
                                               feature_allocations=len(allocations))
                if parts[1] == 'off-clients':
                    self.run.check(feature + ' allocates nothing before first enable', len(allocations), 0)
        self.run.rows[self.path.stem] = dict(snapshots=self.snapshots, attributed_allocations=allocations,
                                            clients=24)
        # Retain raw attribution in the receipt, not an unbounded address log.
        self.path.unlink()


def untraced_rss(run, mode, label, extra, feature):
    """Measure normal resident memory on a fresh process without the C++ tracer."""
    if run.oracle:
        return
    from _serverfix import Server, is_error
    off = ['--slowlog-log-slower-than', '-1', '--latency-monitor-threshold', '0',
           '--acllog-max-len', '0']
    with Server(run, label + '-rss-uninstrumented', mode, extra=extra + off) as server:
        pid = server.process.pid
        traced = 'alloc-trace.so' in Path(f'/proc/{pid}/maps').read_text()
        run.check(label + ' RSS process excludes allocation tracer', traced, False)
        def rss():
            return int(re.search(r'^Rss:\s+(\d+)',
                                 Path(f'/proc/{pid}/smaps_rollup').read_text(), re.M)[1])
        boot = rss()
        with contextlib.ExitStack() as stack:
            clients = [stack.enter_context(server.client()) for _ in range(24)]
            if feature == 'slowlog':
                for i, client in enumerate(clients):
                    run.check(label + ' RSS name ' + str(i),
                              client.cmd('CLIENT', 'SETNAME', 'before-' + str(i)), b'OK')
                run.check(label + ' RSS disabled slowlog', clients[0].cmd('SLOWLOG', 'GET', -1), [])
            else:
                run.check(label + ' RSS user', clients[0].cmd('ACL', 'SETUSER', 'lazy-denied',
                          'on', 'nopass', '+ping', '~*'), b'OK')
                for client in clients[1:]:
                    run.check(label + ' RSS auth', client.cmd('AUTH', 'lazy-denied', ''), b'OK')
                    run.check(label + ' RSS denial', client.cmd('GET', 'denied'),
                              lambda r: is_error(r, 'NOPERM'))
                run.check(label + ' RSS disabled ACL log', clients[0].cmd('ACL', 'LOG'), [])
            run.rows[label + '-rss-uninstrumented'] = dict(
                clients=24, off_boot_rss_kib=boot, off_clients_rss_kib=rss(),
                allocation_tracer_loaded=traced)
