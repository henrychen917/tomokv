import argparse
import atexit
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import srv  # noqa: E402

LOGDIR = os.path.join(srv.ROOT, 'logs')
os.makedirs(LOGDIR, exist_ok=True)


def base_args(desc):
    p = argparse.ArgumentParser(description=desc)
    p.add_argument('--server', choices=['tomokv', 'redis'], default='tomokv')
    p.add_argument('--mode', choices=['2s', '1s'], default='2s')
    p.add_argument('--rl', type=int, default=0)
    p.add_argument('--atomic', type=int, default=0)
    p.add_argument('--port', type=int, default=21001)
    p.add_argument('--attempts', type=int, default=30)
    return p


def boot(a, extra=(), tag=None):
    if a.server == 'redis':
        s = srv.redis(a.port, tag=tag or 'redis')
    else:
        s = srv.tomokv(a.port, a.mode, a.rl, a.atomic, extra=extra, tag=tag)
    # a crashing script must never leak its server: stop it by pid at interpreter exit
    atexit.register(lambda: s.stop() if s.alive() else None)
    return s


def geometry(a, s=None):
    if a.server == 'redis':
        return 'redis-7.4.10 oracle'
    return srv.geometry_name(a.mode, a.rl, a.atomic)


class Log:
    def __init__(self, item, a, variant=''):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        name = '%s-%s-%s%s-%s.jsonl' % (
            item, a.server, geometry(a).replace(' ', '_').replace(':', '-').replace('(', '').replace(')', ''),
            ('-' + variant) if variant else '', stamp)
        self.path = os.path.join(LOGDIR, name)
        self.f = open(self.path, 'w')

    def write(self, **rec):
        self.f.write(json.dumps(rec, default=str) + '\n')
        self.f.flush()

    def close(self):
        self.f.close()
