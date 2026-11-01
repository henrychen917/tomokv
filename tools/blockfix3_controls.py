#!/usr/bin/env python3
"""Blocked-stream publication-boundary control, with bound production objects."""
import argparse
import json
from pathlib import Path
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
    for arm in ('boundary',):
        dest = OUT / arm
        dest.mkdir(parents=True, exist_ok=True)
        link = list(post)
        source = dest / 'source'
        shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
        path = source / 'src/cmd/t_stream_groups.cc'
        # PRE is this lane's base (already containing blockfix2's six
        # passing fixes). Keep POST's stream/server objects so this control
        # changes only the publication boundary, not error accounting.
        keep = ('/t_stream_groups.o', '/t_server.o')
        link = [str(ROOT / 'build/blockfix3/pre-source' / arg)
                if arg.startswith('build/') and arg.endswith('.o') and
                not arg.endswith(keep) else arg for arg in link]
        old.replace(path, '    if (create && shard.has_blocking_waiters())\n'
                    '        blocking_publish_key(shard, op.hash, key.p, key.n, key.ns);', '')
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


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('build', 'check-boundary'))
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.action == 'build': build()
    else: check(a)
