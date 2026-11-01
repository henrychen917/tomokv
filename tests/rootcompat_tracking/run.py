#!/usr/bin/env python3
"""Reuse R2 t1/t3, assert their receipts, and expand to both engines/runtimes."""
import argparse
import json
import os
from pathlib import Path
import traceback

import srv
from authfix import Run
import t1_xsnotify
import t3_keylesscap


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', choices=('xsnotify', 'tracking'), required=True)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--ratio', default='6:2')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    os.environ['LC_ALL'] = 'C'
    failures = 0
    for binary, oracle in ((a.oracle, True), (a.binary, False)):
        run = srv.RUN = Run(a, binary, oracle)
        for mode in run.modes():
            for engine in (['redis'] if oracle else ['uring', 'epoll']):
                for databases in ([16] if oracle else [1, 16]):
                    for atomic in ([0] if oracle else [0, 1]):
                        for read_local in ([0] if oracle else [0, 1]):
                            srv.GEOMETRY = dict(mode=mode, engine=engine, databases=databases,
                                                atomic=atomic, read_local=read_local)
                            label = 'redis' if oracle else f'{mode}-{engine}-db{databases}-a{atomic}-rl{read_local}'
                            out = run.path / (label + '.jsonl')
                            try:
                                if a.case == 'xsnotify':
                                    for force in ([False] if oracle else [False, True]):
                                        target = out.with_suffix('.forced.jsonl') if force else out
                                        t1_xsnotify.run(label, a.port, 3, target, force=force)
                                        result = json.loads(target.read_text())
                                        for shape, row in result['shapes'].items():
                                            key = label + shape + (' escalated' if force else ' staged')
                                            run.check(key + ' armed', row['hits'], 3)
                                            run.check(key + ' ordered events', row['events_ok'], 3)
                                            run.check(key + ' invalidations', row['inval_ok'], 3)
                                else:
                                    # SCAN exercises all geometries. One large MGET independently
                                    # exercises the read-local-off owner path (R2's second witness).
                                    for trigger in ('scan', 'mget'):
                                        if trigger == 'mget' and read_local:
                                            continue
                                        t3_keylesscap.run(label + '-' + trigger if not oracle else label,
                                            a.port, 1, 100000, 4000, trigger, out,
                                            mget_chunk=100000)
                                    for result in map(json.loads, out.read_text().splitlines()):
                                        for row in result['attempts']:
                                            run.check(label + result['trigger'] + ' live enrolment',
                                                      row['dbsize_before_trigger'], 100000)
                                            run.check(label + result['trigger'] + ' no missing keys', row['missing'], 0)
                            except Exception:
                                traceback.print_exc()
                                run.check(label + ' completed witness', False, True)
        failures += run.finish()
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
