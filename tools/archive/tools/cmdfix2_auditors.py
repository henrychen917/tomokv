#!/usr/bin/env python3
"""Rerun the supplied audit code, changing only lifecycle CPUs, ports and paths.

No file under round5-read is edited. Raw receipts retain out-of-scope differences.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from datafix1_common import boot


def main():
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    sys.dont_write_bytecode = True
    p = argparse.ArgumentParser()
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--port', type=int, default=21360)
    p.add_argument('--cores', default='100-107')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--only', choices=('data', 'complex'), default=None)
    a = p.parse_args(); a.output.mkdir(parents=True, exist_ok=True)
    data = Path('/home/user/Projects/round5-read/tests/cmd-data')
    complex_dir = Path('/home/user/Projects/round5-read/tests/cmd-complex')
    sys.path[:0] = [str(data), str(complex_dir)]
    import audit
    import audit_resp
    audit.BASE = a.output.resolve()
    audit.TARGET = str(a.binary.resolve())
    sources = {}

    @contextlib.contextmanager
    def owned(binary, port, flags, where):
        oracle = binary == audit.ORACLE
        port = a.port + int(oracle)
        flags = list(flags)
        if '--place' in flags:
            pos = flags.index('--place'); del flags[pos:pos+2]
        with boot(binary, port, a.cores, where, flags, oracle=oracle):
            c = audit.Conn(port)
            try: yield c
            finally: c.close()
    audit.boot = owned

    def run(file, args, name):
        path = data / file
        sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        sys.argv = [str(path), *args]
        with (a.output / (name + '.jsonl')).open('w') as out, contextlib.redirect_stdout(out):
            try: runpy.run_path(str(path), run_name='__main__')
            except SystemExit as e: print(json.dumps(dict(audit_exit=e.code)))
        print('completed', name, flush=True)

    if a.only != 'complex':
        for mode in ('1s', '2s'):
            for grid in ('polar', 'midlat'):
                run('geo-cover.py', ['--mode', mode, '--grid', grid], f'G-T1-{mode}-{grid}')
            for case in ('cover_radius', 'cover_box', 'mixed_scores'):
                run('geo-witness.py', ['--mode', mode, '--case', case], f'G-T2-T3-{mode}-{case}')
            run('geo-mixed-random.py', ['--mode', mode, '--atomic', '1'], f'G-T3b-{mode}')
            run('geo_probe.py', ['--mode', mode], f'T8-{mode}')
            run('witness.py', ['--case', 'geo_box', '--mode', mode, '--db', '7', '--local', '1', '--atomic', '1'], f'T9-T10-{mode}')
            for group in ('pfmulti', 'multilocal', 'pfsame'):
                for atomic in ('0', '1'):
                    run('str-misc.py', ['--group', group, '--mode', mode, '--atomic', atomic], f'S-T22-T24-{mode}-{group}-a{atomic}')
            # Original n=30000 witness; timing/RSS are observations, never a rate claim.
            run('str-lcsdos.py', ['--mode', mode, '--port', str(a.port)], f'S-T6-{mode}')

    if a.only != 'data':
        for file, label, databases, atomic in [('acl_multi_channel.py', 'T40', 16, 0),
                  ('acl_multi_channel.py', 'T47', 1, 1),
                  ('streams_semantics.py', 'T21', 16, 0),
                  ('streams_xsetid_lag.py', 'T21b', 16, 0)]:
            path = complex_dir / file
            sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            spec = importlib.util.spec_from_file_location('cmdfix2_audit_probe', path)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            for mode in ('oracle', '1s', '2s'):
                oracle = mode == 'oracle'
                binary = audit.ORACLE if oracle else audit.TARGET
                flags = [] if oracle else ['--shards', '16', '--databases', str(databases),
                    '--atomic', str(atomic), '--thread-mode', mode, '--flip-auto', '0']
                if mode == '2s': flags += ['--ratio', '6:2']
                with (a.output / f'{label}-{mode}.jsonl').open('w') as out, contextlib.redirect_stdout(out):
                    with boot(binary, a.port, a.cores, a.output / f'{label}-{mode}', flags, oracle=oracle):
                        result = audit_resp.plain(module.probe(a.port, 'redis' if oracle else 'tomo', mode))
                        print(json.dumps(dict(test=label, mode=mode, result=result)), flush=True)
                print('completed', label, mode, flush=True)
    (a.output / 'source-sha256.json').write_text(json.dumps(sources, indent=2) + '\n')


if __name__ == '__main__':
    main()
