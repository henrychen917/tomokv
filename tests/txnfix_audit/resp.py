# resp.py -- minimal RESP2 client + server lifecycle helpers for the round-4 server-atomics tests.
# Black box only: talks to a running server over TCP. No redis-py.
import argparse, os, socket, subprocess, sys, tempfile, time, signal
from pathlib import Path

# Shared named options are removed before the historical script reads its positional
# workload arguments. --port supplies the historical first positional argument.
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--binary", default="build/tomokv")
_parser.add_argument("--port", type=int)
_parser.add_argument("--cores", default="112-119")
_parser.add_argument("--atomic", choices=("0", "1"))
_parser.add_argument("--mode", choices=("1s", "2s"))
_parser.add_argument("--databases", type=int, default=1)
_parser.add_argument("--shards", type=int, default=16)
_parser.add_argument("--ratio", default="6:2")
_parser.add_argument("--output", default="build/txnfix/audit")
_options, _positional = _parser.parse_known_args()
sys.argv[1:] = ([str(_options.port)] if _options.port else []) + _positional
HEADLINE = str(Path(_options.binary).resolve())
ORACLE = "/home/user/Projects/redis74/src/redis-server"
CPUS = _options.cores
OUTPUT = Path(_options.output).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)



class RespError(Exception):
    pass


class Conn:
    def __init__(self, port, host="127.0.0.1", timeout=10.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass

    @staticmethod
    def enc(*args):
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            if isinstance(a, int):
                a = str(a).encode()
            elif isinstance(a, str):
                a = a.encode()
            out.append(b"$%d\r\n%s\r\n" % (len(a), a))
        return b"".join(out)

    def send(self, *args):
        self.s.sendall(self.enc(*args))

    def send_many(self, cmds):
        self.s.sendall(b"".join(self.enc(*c) for c in cmds))

    def _fill(self):
        chunk = self.s.recv(1 << 20)
        if not chunk:
            raise ConnectionError("closed")
        self.buf += chunk

    def _line(self):
        while True:
            i = self.buf.find(b"\r\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 2:]
                return line
            self._fill()

    def _exact(self, n):
        while len(self.buf) < n + 2:
            self._fill()
        data, self.buf = self.buf[:n], self.buf[n + 2:]
        return data

    def read(self):
        line = self._line()
        t, rest = line[:1], line[1:]
        if t == b"+":
            return rest.decode()
        if t == b"-":
            return RespError(rest.decode())
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            return None if n < 0 else self._exact(n)
        if t == b"*":
            n = int(rest)
            return None if n < 0 else [self.read() for _ in range(n)]
        if t == b"_":
            return None
        if t == b",":
            return float(rest)
        if t == b"%":
            n = int(rest)
            return {self.read(): self.read() for _ in range(n)}
        if t == b"=":
            n = int(rest)
            return self._exact(n)
        raise ValueError("unknown RESP type %r" % line)

    def cmd(self, *args):
        self.send(*args)
        return self.read()

    def pipeline(self, cmds):
        self.send_many(cmds)
        return [self.read() for _ in cmds]

    def settimeout(self, t):
        self.s.settimeout(t)


def info(conn, section=None):
    raw = conn.cmd("INFO", section) if section else conn.cmd("INFO")
    out = {}
    for line in raw.decode().split("\r\n"):
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            out[k] = v
    return out


def port_open(port):
    r = subprocess.run(["ss", "-ltnH", "sport = :%d" % port], capture_output=True, text=True)
    return bool(r.stdout.strip())


class Server:
    """Start a server pinned to our cores; record the PID of the server process itself."""

    def __init__(self, port, args=(), binary=HEADLINE, cpus=CPUS, log=None, oracle=False):
        assert 22600 <= port <= 22699, "port outside the server-atomics range"
        if port_open(port):
            raise RuntimeError("port %d already in use" % port)
        self.port = port
        self.log = log or str(OUTPUT / ("srv-%d.log" % port))
        os.makedirs(os.path.dirname(self.log), exist_ok=True)
        args = list(args)
        if not oracle:
            for flag, value in (("--thread-mode", _options.mode), ("--atomic", _options.atomic),
                                ("--shards", str(_options.shards)), ("--ratio", _options.ratio),
                                ("--databases", str(_options.databases)), ("--key-lb", "0"),
                                ("--client-lb", "0"), ("--flip-auto", "0")):
                if value is None:
                    continue
                if flag in args:
                    index = args.index(flag)
                    args[index + 1] = value
                else:
                    args.extend((flag, value))
        if oracle:
            argv = ["taskset", "-c", cpus, ORACLE, "--bind", "127.0.0.1", "--port", str(port),
                    "--save", "", "--appendonly", "no"] + list(args)
        else:
            argv = ["taskset", "-c", cpus, binary, "--bind", "127.0.0.1", "--port", str(port),
                    "--save", "", "--appendonly", "no"] + list(args)
        self.argv = argv
        self.logf = open(self.log, "w")
        # taskset execs the server binary, so Popen.pid IS the server process.
        self.proc = subprocess.Popen(argv, stdout=self.logf, stderr=subprocess.STDOUT,
                                     cwd=str(OUTPUT))
        self.pid = self.proc.pid
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("server exited rc=%s; see %s" % (self.proc.returncode, self.log))
            try:
                c = Conn(port, timeout=2)
                if c.cmd("PING") == "PONG":
                    c.close()
                    return
                c.close()
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError("server did not answer PING on %d" % port)

    def conn(self, timeout=10.0):
        return Conn(self.port, timeout=timeout)

    def stop(self, sig=signal.SIGTERM, wait=30):
        if self.proc.poll() is None:
            os.kill(self.pid, sig)
            try:
                self.proc.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                os.kill(self.pid, signal.SIGKILL)
                self.proc.wait(timeout=10)
        self.logf.close()
        for _ in range(50):
            if not port_open(self.port):
                break
            time.sleep(0.1)
        assert not port_open(self.port), "port %d still open after stop" % self.port
        return self.proc.returncode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()
