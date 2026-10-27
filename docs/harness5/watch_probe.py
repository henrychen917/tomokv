"""Per-boot probe for WATCH-SPURIOUS-INVALIDATION (unit/type/set "SMOVE only notify dstset ...").

SMOVE srcset{t} dstset{t} a, where dstset{t} already holds a, leaves dstset{t} unchanged, so Redis
does not invalidate a WATCH on it and the watching transaction commits. The upstream test failed
once on TomoKV while the gated subset was built; within one boot the outcome is fixed, so this
probe boots a FRESH server per trial (TomoKV seeds its key hash per process) and runs the upstream
sequence a few times per boot. Output: per-mode count of boots whose EXEC aborted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repro_tcl as R

SEQUENCE = (['DEL', 'srcset{t}', 'dstset{t}'], ['SADD', 'srcset{t}', 'a', 'b'], ['SADD', 'dstset{t}', 'a'],
            ['WATCH', 'dstset{t}'], ['MULTI'], ['SADD', 'dstset{t}', 'c'])


def trial(mode, options, folder):
    binary = R.REDIS if mode == 'redis' else options.binary
    process, argv = R.boot(mode, binary, options.port, options.cores, options.ratio, [], folder)
    outcomes = []
    try:
        a = R.Client(options.port)
        for _ in range(options.iterations):
            for command in SEQUENCE:
                a.send(command); a.read()
            b = R.Client(options.port)  # upstream opens a fresh client for the SMOVE
            b.send(['SMOVE', 'srcset{t}', 'dstset{t}', 'a']); moved = b.read(); b.close()
            a.send(['EXEC']); executed = a.read()
            a.send(['SCARD', 'dstset{t}']); card = a.read()
            outcomes.append(dict(smove=moved, exec=executed, scard=card))
        a.close()
    finally:
        R.stop(process)
    return dict(server_argv=argv, outcomes=outcomes, aborted=sum(o['exec'] is None for o in outcomes))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--boots', default='2s=30,1s=60,redis=30')
    p.add_argument('--iterations', type=int, default=5)
    p.add_argument('--binary', type=Path, default=HERE.parents[1] / 'build/tomokv')
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--ratio', default='6:2')
    options = p.parse_args()
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(binary_sha256=sha(options.binary), redis_sha256=sha(R.REDIS), iterations=options.iterations,
                  modes={})
    work = HERE.parents[1] / 'build/h5-watch-probe'
    for spec in options.boots.split(','):
        mode, count = spec.split('=')
        boots = [trial(mode, options, work / f'{mode}-{i}') for i in range(int(count))]
        report['modes'][mode] = dict(boots=len(boots), boots_with_abort=sum(b['aborted'] > 0 for b in boots),
                                     boots_all_aborted=sum(b['aborted'] == options.iterations for b in boots),
                                     trials=boots)
        print(mode, report['modes'][mode]['boots_with_abort'], '/', len(boots), 'boots aborted', flush=True)
    options.output.write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
