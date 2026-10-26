"""Reach the upstream assertions that an interrupted file never ran.

The full-file survey stops a file at the first hung test (idle deadline) or at a
file-level exception. This helper reruns such a file with every hung test named
in a --skipfile (and, where a file-level setup cannot run on TomoKV, an explicit
--tags exclusion), so the remaining assertions execute. Discovery iterates per
TomoKV mode until the file completes; the final evidence then runs TomoKV 2s,
TomoKV 1s and Redis 7.4.10 with the SAME union skip list and tags, so a newly
reached result is compared like for like. No assertion body is modified.
"""
import argparse
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl as suite

REDIS = Path('/home/user/Projects/redis/src/redis-server')
# File-level setup that aborts the whole file on TomoKV in external mode.
TAGS = {'unit/type/stream': ['--tags', '-needs:debug']}


def hung_test(row):
    """Name of a test that started and never reported a verdict, if any."""
    open_tests = []
    for event in row['events']:
        name = event['test'].split(' in tests/')[0]
        if event['status'] == 'testing':
            open_tests.append(name)
        elif event['status'] in ('ok', 'err', 'skip', 'ignore') and name in open_tests:
            open_tests.remove(name)
    return open_tests[-1] if open_tests else None


def run(options, unit, mode, skips, tag, idle, label):
    binary = REDIS if mode == 'redis' else options.binary
    output = options.output / label / mode
    skipfile = output / 'skip.txt'
    output.mkdir(parents=True, exist_ok=True)
    skipfile.write_text(''.join(name + '\n' for name in skips), encoding='utf-8')
    args = argparse.Namespace(output=output, binary=binary, mode=mode, cores=options.cores,
                              port=options.port, baseport=options.baseport, idle_timeout=idle,
                              file_timeout=options.file_timeout, ratio='6:2')
    extra = ['--skipfile', str(skipfile), *tag]
    row = suite.run_file(args, options.tree, unit, extra=extra)
    row['skip_tests'] = list(skips)
    row['extra_runtest_args'] = ['--skipfile', '<skip_tests>', *tag]
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--files', required=True)
    p.add_argument('--modes', default='2s,1s')
    p.add_argument('--final-modes', default='')
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cores', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--controller-port', type=int, required=True)
    p.add_argument('--baseport', type=int, required=True)
    p.add_argument('--discovery-idle', type=int, default=30)
    p.add_argument('--file-timeout', type=int, default=300)
    p.add_argument('--skips-json', type=Path, help='final pass: {file: [names]} from discovery')
    options = p.parse_args()
    options.output = options.output.resolve(); options.binary = options.binary.resolve()
    options.tree = options.output / 'checkout'
    suite.prepare(Path('/home/user/Projects/redis'), options.tree, controller_port=options.controller_port)
    report = dict(binary_sha256=suite.sha(options.binary), redis_sha256=suite.sha(REDIS), rows=[])
    for unit in options.files.split(','):
        tag = TAGS.get(unit, [])
        if options.skips_json:
            skips = json.loads(options.skips_json.read_text()).get(unit, [])
            for mode in options.final_modes.split(','):
                row = run(options, unit, mode, skips, tag, 60, 'final/' + unit)
                row['phase'] = 'final'
                report['rows'].append(row)
                print(f"final {mode} {unit}: {row['passed']} pass {row['failed']} fail "
                      f"{row['skipped']} skip complete={row['complete']} hung={hung_test(row)}", flush=True)
        else:
            for mode in options.modes.split(','):
                skips = []
                for attempt in range(12):
                    row = run(options, unit, mode, skips, tag, options.discovery_idle,
                              f'discovery/{unit}/{attempt}')
                    row['phase'] = 'discovery'; row['attempt'] = attempt
                    report['rows'].append(row)
                    name = hung_test(row)
                    print(f"discovery {mode} {unit} #{attempt}: {row['passed']} pass {row['failed']} fail "
                          f"complete={row['complete']} hung={name}", flush=True)
                    if row['complete'] or not name or name in skips:
                        break
                    skips.append(name)
        (options.output / 'report.json').write_text(json.dumps(report, indent=1) + '\n')
    (options.output / 'report.json.gz').write_bytes(
        gzip.compress(json.dumps(report, sort_keys=True).encode(), mtime=0))


if __name__ == '__main__':
    main()
