"""Gate-owned lifecycle adapter for the owner's R2 tracking reproducers."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from authfix import Server as GateServer
from resp import Conn

RUN = None
GEOMETRY = None
SERIAL = 0


def geometry_text(name):
    return {'name': name, **GEOMETRY, 'cores': RUN.args.cores, 'ratio': RUN.args.ratio}


class Server:
    def __init__(self, name, port, tag='x'):
        global SERIAL
        SERIAL += 1
        self.port = port
        extra = ['--databases', str(GEOMETRY['databases']), '--enable-debug-command', 'yes']
        if not RUN.oracle:
            extra += ['--net-io', GEOMETRY['engine'], '--atomic', str(GEOMETRY['atomic']),
                      '--read-local', str(GEOMETRY['read_local']), '--key-lb', '0', '--client-lb', '0']
        self.inner = GateServer(RUN, f'{tag}-{name}-{SERIAL}', GEOMETRY['mode'], extra=extra)
        self.argv = self.inner.args

    def start(self):
        self.inner.__enter__()

    def stop(self):
        self.inner.__exit__(None, None, None)

    def conn(self, timeout=5.0, name=None):
        return Conn(self.port, timeout=timeout, name=name)


def shards_of(conn, keys):
    return [(int(shard), int(owner)) for shard, owner in conn.call('DEBUG', 'SHARDS', *keys)]
