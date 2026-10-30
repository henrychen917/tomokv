#!/usr/bin/env python3
"""Boundary-only and NOGROUP-accounting controls, with bound production objects."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/blockfix3/controls'
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl
import blockfix2_controls as old


def build():
    post = old.recipe('build/tomokv')
    records = {}
    for arm in ('boundary', 'statistics'):
        dest = OUT / arm
        dest.mkdir(parents=True, exist_ok=True)
        link = list(post)
        source = dest / 'source'
        shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
        path = source / 'src/cmd/t_stream_groups.cc'
        if arm == 'boundary':
            # PRE is this lane's base (already containing blockfix2's six
            # passing fixes). Keep POST's statistics objects so only the
            # publication boundary is removed.
            keep = ('/t_stream_groups.o', '/t_server.o')
            link = [str(ROOT / 'build/blockfix3/pre-source' / arg)
                    if arg.startswith('build/') and arg.endswith('.o') and
                    not arg.endswith(keep) else arg for arg in link]
            old.replace(path, '    if (create && shard.has_blocking_waiters())\n'
                        '        blocking_publish_key(shard, op.hash, key.p, key.n, key.ns);', '')
        else:
            old.replace(path, 'if (xreadgroup) xreadgroup_nogroup.fetch_add',
                        'if (false && xreadgroup) xreadgroup_nogroup.fetch_add')
        for namespace in ('', 'db0/'):
            target = 'build/' + namespace + 'src/cmd/t_stream_groups.o'
            command = old.recipe(target)
            command = [str(path) if arg == 'src/cmd/t_stream_groups.cc' else arg for arg in command]
            obj = dest / ('db0.o' if namespace else 'normal.o')
            command[command.index('-o') + 1] = str(obj)
            subprocess.run(command, cwd=ROOT, check=True)
            link = [str(obj) if arg == target else arg for arg in link]
        link[link.index('-o') + 1] = str(dest / 'tomokv')
        subprocess.run(link, cwd=ROOT, check=True)
        record = dict(post_sha256=redis_tcl.sha(ROOT / 'build/tomokv'),
                      binary_sha256=redis_tcl.sha(dest / 'tomokv'), link=link)
        (dest / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        records[arm] = record
        if (dest / 'source').exists(): shutil.rmtree(dest / 'source')
    (ROOT / 'docs/blockfix3/controls.json').write_text(json.dumps(records, indent=2) + '\n')


def check(args):
    record = json.loads((OUT / 'boundary/receipt.json').read_text())
    assert record['post_sha256'] == redis_tcl.sha(args.binary)
    assert record['binary_sha256'] == redis_tcl.sha(OUT / 'boundary/tomokv')
    logs = list(args.output.glob('removed-db*-*.log'))
    assert len(logs) == 24, len(logs)
    for path in logs:
        text = path.read_text()
        assert 'GEOMETRY ' in text, path
        assert "deleted group's waiter must not consume recreated stream" in text, path
        assert 'never woke its group reader' not in text, path
    print('boundary-only control: all 24 legs reach and reject pipelined recreation')


def tcl(args):
    # Use the unchanged required Tcl test and the exact validator used by the
    # complete Tcl job. Its reply assertion passes on this control; stats fail.
    arm = 'statistics'
    record = json.loads((OUT / arm / 'receipt.json').read_text())
    assert record['post_sha256'] == redis_tcl.sha(args.binary)
    name = 'XGROUP DESTROY should unblock XREADGROUP with -NOGROUP'
    unit = 'unit/type/stream-cgroups'
    manifest = json.loads((ROOT / 'tests/redis_tcl_passing.json').read_text())
    expected = [x for x in manifest['files'][unit]['passed_tests'] if x.split(' in tests/')[0] == name]
    assert len(expected) == 1
    args.output.mkdir(parents=True, exist_ok=True)
    tree = args.output / 'checkout'
    redis_tcl.prepare(args.redis_root, tree, controller_port=args.port + 1)
    rows = []
    for mode in ('1s', '2s'):
        for label, binary in [('POST', args.binary), ('BROKEN', OUT / arm / 'tomokv')]:
            run = argparse.Namespace(output=args.output / mode / label, binary=binary,
                cores=args.cores, port=args.port, baseport=args.port + 2, mode=mode,
                ratio='6:2', idle_timeout=15, file_timeout=45)
            row = redis_tcl.run_file(run, tree, unit, only=[name])
            passed = True
            try: redis_tcl.validate_passing(row, expected, manifest['files'][unit].get('known_setup_errors', ()))
            except ValueError: passed = False
            row.update(arm=label, validated=passed, sha256=redis_tcl.sha(binary))
            rows.append(row)
            (args.output / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
            assert passed if label == 'POST' else (not passed and any(
                e['status'] == 'err' and 'errorrstat NOGROUP' in e['data'] for e in row['events']))
            print(mode, label, 'PASS' if passed else 'REJECTED', flush=True)
    shutil.rmtree(tree)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('build', 'check-boundary', 'check-tcl'))
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--output', type=Path)
    p.add_argument('--cores', default='0-7')
    p.add_argument('--port', type=int, default=20100)
    p.add_argument('--redis-root', type=Path, default=Path('/home/user/Projects/redis'))
    a = p.parse_args()
    if a.action == 'build': build()
    elif a.action == 'check-boundary': check(a)
    else: tcl(a)
