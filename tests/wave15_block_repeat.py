#!/usr/bin/env python3
"""Repeat the unchanged deleted-stream row on fresh state, with no skipped arms."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import traceback

from _lib import Conn, info, topology
from cfgfix2 import Server
from compat3_blockfix2 import probe
from compat3_lib import equal, wire


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'oracle', 'cores', 'mode', 'engine'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--databases', type=int, choices=(1, 16), required=True)
    p.add_argument('--read-local', type=int, choices=(0, 1), required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    os.environ['LC_ALL'] = 'C'
    a.output.mkdir(parents=True, exist_ok=False)
    with Server(a, 'oracle', 'redis', 'oracle'):
        with closing(Conn('127.0.0.1', a.port, timeout=8, buffering=0)) as c:
            assert info(c, 'server')['redis_version'].startswith('7.4.')
            c.must('FLUSHALL')
            expected = probe(c, 'removed')
    (a.output/'oracle.json').write_text(json.dumps(wire(expected), indent=2)+'\n')
    result = dict(binary_sha256=hashlib.sha256(Path(a.binary).read_bytes()).hexdigest(),
                  mode=a.mode, engine=a.engine, atomic=1, databases=a.databases,
                  read_local=a.read_local, requested=200, completed=0, passed=False)
    try:
        with Server(a, 'target', a.mode, a.engine, extra=[
                '--atomic', '1', '--databases', str(a.databases),
                '--read-local', str(a.read_local), '--enable-debug-command', 'yes']):
            with closing(Conn('127.0.0.1', a.port, timeout=8, buffering=0)) as c:
                observed = info(c, 'server')
                for key, value in dict(thread_mode=a.mode, net_io=a.engine, atomic='1',
                                       read_local=str(a.read_local), shards='16').items():
                    equal(observed[key], value, 'geometry '+key)
                roles = list(topology(c).roles.values())
                equal(sorted(roles), sorted(['io']*6+['ex']*2 if a.mode=='2s' else ['fused']*8),
                      'landing geometry')
                with (a.output/'iterations.jsonl').open('w') as log:
                    for i in range(200):
                        c.must('FLUSHALL')
                        actual = probe(c, 'removed')
                        equal(actual, expected, f'iteration {i+1} exact oracle observations')
                        result['completed'] = i+1
                        record = dict(iteration=i+1, passed=True)
                        log.write(json.dumps(record)+'\n'); log.flush()
                        print(json.dumps(record), flush=True)
        result['passed'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    (a.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
