#!/usr/bin/env python3
"""Build a disposable crossing-group scheduler; production sources stay untouched.

Only the two xshard objects are rebuilt. Every other object and the link order come
from the selected arm's ordinary Makefile. The hook parks one fragment per group
before installation; it never changes the command, MVCC decision or AOF bytes.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile


HOOK = '''
    // Disposable aoforder scheduling hook: two groups install in opposite shard orders.
    if (state.atomic_write && state.kind == Kind::Mset && op.argc() == 5) {
        const char* release = std::getenv("TOMO_AOFORDER_CROSS_RELEASE");
        const bool first = op.arg(2).eq_icase("aoforder-group1");
        const bool second = op.arg(2).eq_icase("aoforder-group2");
        const uint32_t delayed = first ? 1 : 0;
        if (release && (first || second) &&
            state.keys[delayed].shard == shard.id() && ::access(release, F_OK) != 0)
            return ScatterTaskResult::Defer;
    }
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--objects', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ref', help='source revision for a historical arm; default: current files')
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    output, objects = args.output.resolve(), args.objects.resolve()
    assert output.is_relative_to(root / 'build') and objects.is_relative_to(root / 'build')
    output.mkdir(parents=True, exist_ok=True)
    source = output / 'source'
    source.mkdir(exist_ok=True)
    affinity = ','.join(map(str, sorted(os.sched_getaffinity(0))))
    prefix = ['taskset', '-c', affinity]
    if args.ref:
        archive = subprocess.check_output(prefix + ['git', 'archive', args.ref,
                                                   'src', 'third_party', 'Makefile'], cwd=root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter='data')
    else:
        for name in ('src', 'third_party'):
            shutil.copytree(root / name, source / name, dirs_exist_ok=True)
        shutil.copy2(root / 'Makefile', source / 'Makefile')
    path = source / 'src/cmd/scatter_engine.inc'
    text = path.read_text()
    anchor = '    // ONE EXPIRY CUT FOR THE WHOLE FAN-OUT.'
    assert text.count(anchor) == 1
    path.write_text(text.replace(anchor, HOOK + anchor))
    dry = subprocess.check_output(prefix + ['make', '-n', '-B',
        f'BUILD_ROOT={objects}', 'all'], cwd=source, text=True)
    commands = [shlex.split(line) for line in dry.splitlines()
                if line.startswith(('g++ ', 'c++ ', 'clang++ '))]
    compiles = [cmd for cmd in commands if '-c' in cmd and 'src/cmd/xshard.cc' in cmd]
    assert len(compiles) == 2
    replacements = {}
    for index, cmd in enumerate(compiles):
        pos = cmd.index('-o') + 1
        replacements[cmd[pos]] = str(output / f'xshard-{index}.o')
        cmd[pos] = replacements[cmd[pos]]
    link, = [cmd for cmd in commands if '-c' not in cmd]
    link = [replacements.get(arg, arg) for arg in link]
    link[link.index('-o') + 1] = str(output / 'tomokv')
    def run(pair):
        index, cmd = pair
        with (output / f'compile-{index}.log').open('w') as log:
            subprocess.run(prefix + cmd, cwd=source, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, enumerate(compiles)))
    with (output / 'link.log').open('w') as log:
        subprocess.run(prefix + link, cwd=source, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    (output / 'commands.json').write_text(json.dumps({
        'ref': args.ref, 'affinity': affinity,
        'compile': [prefix + c for c in compiles], 'link': prefix + link}, indent=2) + '\n')


if __name__ == '__main__':
    main()
