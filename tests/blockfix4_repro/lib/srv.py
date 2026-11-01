"""Boot/stop helpers. Rules: caller-assigned CPUs and ports, LC_ALL=C,
port check before every boot, pid file, stop by that pid (never pkill/killall)."""
import os
import re
import signal
import subprocess
import time

from resp import Conn, Err

ROOT = os.environ['BLOCKFIX4_OUTPUT']
TOMOKV = os.environ['BLOCKFIX4_BINARY']
REDIS = os.environ['BLOCKFIX4_ORACLE']
CPUS = os.environ['BLOCKFIX4_CORES']


def port_listening(port):
    out = subprocess.run(['ss', '-ltnp'], capture_output=True, text=True).stdout
    return any(re.search(r':%d\s' % port, line) for line in out.splitlines())


def geometry_name(mode, rl, atomic):
    if mode == '2s':
        return '2s ratio 6:2 shards16 rl%d a%d' % (rl, atomic)
    return '1s fused(8) shards16 rl%d a%d' % (rl, atomic)


class Server:
    def __init__(self, kind, port, args, tag):
        assert 0 < port < 32768, 'explicit test port must be below the ephemeral range'
        self.kind, self.port, self.tag = kind, port, tag
        if port_listening(port):
            raise RuntimeError('port %d already has a listener; refusing to boot' % port)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        self.dir = os.path.join(ROOT, 'run', '%s-%s-%d' % (tag, stamp, os.getpid()))
        os.makedirs(self.dir, exist_ok=True)
        self.pidfile = os.path.join(self.dir, 'server.pid')
        self.logpath = os.path.join(self.dir, 'server.log')
        env = dict(os.environ)
        env['LC_ALL'] = 'C'
        binary = TOMOKV if kind == 'tomokv' else REDIS
        if kind == 'tomokv':
            argv = [binary, '--port', str(port), '--bind', '127.0.0.1', '--shards', '16',
                    '--dir', self.dir, '--save', '', '--databases', os.environ.get('BLOCKFIX4_DATABASES', '1'),
                    '--net-io', os.environ['BLOCKFIX4_ENGINE']] + args
        else:
            argv = [binary, '--port', str(port), '--bind', '127.0.0.1', '--save', '',
                    '--appendonly', 'no', '--dir', self.dir, '--daemonize', 'no',
                    '--enable-debug-command', 'yes'] + args
        self.argv = ['taskset', '-c', CPUS, 'env', 'LC_ALL=C'] + argv
        self.log = open(self.logpath, 'w')
        # taskset and env both exec(), so the Popen pid IS the server pid.
        self.proc = subprocess.Popen(self.argv, stdout=self.log, stderr=subprocess.STDOUT,
                                     env=env, start_new_session=True)
        with open(self.pidfile, 'w') as f:
            f.write('%d\n' % self.proc.pid)
        deadline = time.time() + 30
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError('server exited at boot; log %s' % self.logpath)
            try:
                c = Conn(port, timeout=2)
                r = c.cmd('PING')
                c.close()
                if r == 'PONG':
                    break
            except OSError:
                pass
            if time.time() > deadline:
                self.stop()
                raise RuntimeError('server never answered PING')
            time.sleep(0.05)
        self.version = self._version()
        self.bootline = self._bootline()

    def _version(self):
        out = subprocess.run(['taskset', '-c', CPUS, 'env', 'LC_ALL=C',
                              TOMOKV if self.kind == 'tomokv' else REDIS, '--version'],
                             capture_output=True, text=True).stdout.strip()
        return out

    def _bootline(self):
        time.sleep(0.05)
        try:
            with open(self.logpath) as f:
                for line in f:
                    if line.startswith('tomokv-cpp:'):
                        return line.strip()
        except OSError:
            pass
        return ''

    def conn(self, timeout=10.0):
        return Conn(self.port, timeout=timeout)

    def alive(self):
        return self.proc.poll() is None

    def stop(self):
        try:
            with open(self.pidfile) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            pid = self.proc.pid
        assert pid == self.proc.pid
        if self.proc.poll() is None:
            # Confirm the pid is still our binary before signalling it.
            try:
                exe = os.readlink('/proc/%d/exe' % pid)
            except OSError:
                exe = ''
            if exe and os.path.basename(exe) not in (os.path.basename(TOMOKV), 'redis-server'):
                raise RuntimeError('pid %d is %s, not our server' % (pid, exe))
            os.kill(pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.kill(pid, signal.SIGKILL)
                self.proc.wait(timeout=10)
        self.log.close()
        try:
            os.unlink(self.pidfile)
        except OSError:
            pass
        # the port must be released
        for _ in range(100):
            if not port_listening(self.port):
                break
            time.sleep(0.05)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def tomokv(port, mode, rl, atomic, extra=(), tag=None):
    args = ['--read-local', str(rl), '--atomic', str(atomic), '--enable-debug-command', 'yes']
    if mode == '2s':
        args = ['--ratio', '6:2'] + args
    else:
        args = ['--thread-mode', 'fused'] + args
    return Server('tomokv', port, args + list(extra),
                  tag or 'tomokv-%s-rl%d-a%d' % (mode, rl, atomic))


def redis(port, extra=(), tag='redis'):
    return Server('redis', port, list(extra), tag)


def shards_of(conn, *keys):
    """DEBUG SHARDS -> list of (shard, owner)."""
    r = conn.cmd('DEBUG', 'SHARDS', *keys)
    if isinstance(r, Err):
        raise RuntimeError(r)
    return [(int(a), int(b)) for a, b in r]


def pick_keys(conn, prefix, want, tries=4000, outer=25):
    """Place keys per spec list, e.g. [{'name':'src'}, {'name':'dst','owner_ne':'src'}].
    If a later constraint cannot be met for the first picks (key-LB can leave an owner with one
    shard), start over with fresh names, up to `outer` times."""
    for o in range(outer):
        chosen, placed, ok_all = {}, {}, True
        for spec in want:
            constrained = any(c in spec for c in ('shard_eq', 'shard_ne', 'owner_eq', 'owner_ne'))
            for i in range(tries if constrained else 1):
                k = '%s:%s:%d' % (prefix, spec['name'], i) if o == 0 else \
                    '%s:r%d:%s:%d' % (prefix, o, spec['name'], i)
                sh, ow = shards_of(conn, k)[0]
                ok = True
                if 'shard_eq' in spec and sh != placed[spec['shard_eq']][0]:
                    ok = False
                if 'shard_ne' in spec and sh == placed[spec['shard_ne']][0]:
                    ok = False
                if 'owner_eq' in spec and ow != placed[spec['owner_eq']][1]:
                    ok = False
                if 'owner_ne' in spec and ow == placed[spec['owner_ne']][1]:
                    ok = False
                if ok:
                    chosen[spec['name']] = k
                    placed[spec['name']] = (sh, ow)
                    break
            else:
                ok_all = False
                break
        if ok_all:
            return chosen, placed
    raise RuntimeError('could not place %r' % want)
