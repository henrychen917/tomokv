#!/usr/bin/env python3
"""AT4.12 headline reproduction in the af5 shape, PRE vs POST. Refusal counts and exact data only.

Reuses docs/atomfix5/reproduce.py unchanged: EVAL and FCALL of a two-owner INCR script, 8 clients
x 50 batches x pipeline 16 = 6,400 calls per command; and the cut window, 64 clients each sending
one read-only two-owner EVAL under SCRIPT-STAGE-DEFER 250 ms. No rate is measured. Only the port
and the CPU list differ from the original (this lane's allocation).
"""
import argparse
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'docs/atomfix5'))
import reproduce as af5  # noqa: E402
from atomfix5 import boot  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', required=True)
    p.add_argument('--oracle', default='/home/user/Projects/redis74/src/redis-server')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--port', type=int, default=20200)
    p.add_argument('--cores', default='48-55')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for mode in ('1s', '2s'):
        for atomic in (0, 1):
            label = f'{mode}-atomic{atomic}'
            flags = ['--shards', '16', '--thread-mode', mode, '--atomic', str(atomic),
                     '--databases', '16', '--net-io', 'uring', '--read-local', '1' if mode == '1s' else '0',
                     '--key-lb', '0', '--client-lb', '0', '--flip-auto', '0']
            if mode == '2s':
                flags += ['--ratio', '6:2']
            with boot(args.binary, args.cores, args.port, args.output / label, flags) as admin:
                keys = af5.pair(admin)
                for case in ('scripts', 'script_window'):
                    try:
                        record = dict(leg=label, case=case,
                                      result=getattr(af5, case)(admin, args.port, keys))
                    except Exception:
                        record = dict(leg=label, case=case, error=traceback.format_exc())
                    print(json.dumps(record), flush=True)
                    results.append(record)
    with boot(args.oracle, args.cores, args.port, args.output / 'oracle', ['--databases', '16'], True) as admin:
        record = dict(leg='Redis7.4', case='scripts',
                      result=af5.scripts(admin, args.port, ['atomfix5:a', 'atomfix5:b']))
        print(json.dumps(record), flush=True)
        results.append(record)
    (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    return any('error' in r for r in results)


if __name__ == '__main__':
    raise SystemExit(main())
