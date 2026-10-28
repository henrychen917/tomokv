#!/usr/bin/env python3
"""Fresh-server, bounded PRE/POST/oracle checks for full-job Tcl failures."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl

CASES = {
    'unit/introspection': 'MONITOR log blocked command only once',
    'unit/pubsub': 'PUBLISH/SUBSCRIBE after UNSUBSCRIBE without arguments',
    'unit/slowlog': 'SLOWLOG - Rewritten commands are logged as their original command',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=8)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    tree = args.output / 'checkout'
    redis_tcl.prepare(Path('/home/user/Projects/redis'), tree, controller_port=20191)
    specs = json.loads((ROOT / 'tests/redis_tcl_passing.json').read_text())['files']
    arms = [('pre', ROOT / 'build/blockfix3/pre/tomokv'),
            ('post', ROOT / 'build/blockfix3/post/tomokv'),
            ('oracle', Path('/home/user/Projects/redis74/src/redis-server'))]
    rows = []
    for arm, binary in arms:
        for mode in (('redis',) if arm == 'oracle' else ('1s', '2s')):
            for repeat in range(args.repeats):
                for unit, test in CASES.items():
                    run = argparse.Namespace(output=args.output / arm / mode / str(repeat),
                        binary=binary, cores='0-7', port=20190, baseport=20192,
                        mode=mode, ratio='6:2', idle_timeout=20, file_timeout=90)
                    spec = specs[unit]
                    row = redis_tcl.run_file(run, tree, unit, only=[test],
                        extra=spec.get('extra_args', ()), server_args=spec.get('server_args', ()))
                    expected = [s for s in spec['passed_tests'] if s.split(' in tests/')[0] == test]
                    assert len(expected) == 1, (unit, expected)
                    try:
                        redis_tcl.validate_passing(row, expected,
                            spec.get('known_setup_errors', ()) if mode != 'redis' else ())
                        validated = True
                    except ValueError:
                        validated = False
                    rows.append(dict(arm=arm, mode=mode, repeat=repeat, file=unit,
                        binary_sha256=redis_tcl.sha(binary), validated=validated,
                        passed=row['passed'], failed=row['failed'], error=row['error'],
                        errors=[e for e in row['events'] if e['status'] == 'err']))
                    (args.output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
                    print(arm, mode, repeat, unit, 'PASS' if validated else 'FAIL', flush=True)


if __name__ == '__main__':
    main()
