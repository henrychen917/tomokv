#!/usr/bin/env python3
"""Build throwaway, single-mechanism negative controls; never runs them or a server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import difflib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def command(target, source):
    lines = subprocess.check_output(['make', '-n', '-B', str(target)], cwd=ROOT,
                                    text=True).splitlines()
    return next(shlex.split(line) for line in lines
                if line.startswith('g++ ') and source in line)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('controls', nargs='+', choices=('no-wake', 'no-acl', 'no-hold'))
    args = p.parse_args()
    original = (ROOT / 'src/cmd/blocking.inc').read_text()
    debug_original = (ROOT / 'src/cmd/blocking_debug.cc').read_text()
    jobs = []
    folders = []
    for control in args.controls:
        folder = ROOT / 'build/aclkeys3' / control
        folder.mkdir(parents=True, exist_ok=True)
        folders.append(folder)
        debug_text = debug_original
        if control == 'no-wake':
            old = '        blocking_notify_sender(server, self, ring, client);'
            assert original.count(old) == 1, 'notification control must name the final publisher'
            text = original.replace(old, '        (void)server; (void)client;')
        elif control == 'no-acl':
            old = ('    acl_recheck_blocking(client, client.rob().at(block->op_id),\n'
                   '                         server.thread(client.ifid_thread()));\n')
            assert original.count(old) == 1
            text = original.replace(old, '')
        else:
            old = 'debug_xread_hold.store(static_cast<uint32_t>(stage), std::memory_order_release);'
            assert debug_original.count(old) == 1
            text = original
            debug_text = debug_original.replace(old, 'debug_xread_hold.store(0, std::memory_order_release);')
        (folder / 'blocking.inc').write_text(text)
        (folder / 'blocking_debug.cc').write_text(debug_text)
        (folder / 'control.diff').write_text(''.join(difflib.unified_diff(
            original.splitlines(True), text.splitlines(True),
            fromfile='POST/src/cmd/blocking.inc', tofile=control + '/blocking.inc')) +
            ''.join(difflib.unified_diff(debug_original.splitlines(True), debug_text.splitlines(True),
                    fromfile='POST/src/cmd/blocking_debug.cc', tofile=control + '/blocking_debug.cc')))
        main = (ROOT / 'src/cmd/xshard.cc').read_text()
        assert main.count('#include "blocking.inc"') == 1
        main = main.replace('#include "blocking.inc"', '#include ' + json.dumps(str(folder / 'blocking.inc')))
        (folder / 'xshard.cc').write_text(main)
        for variant in ('src', 'db0/src'):
            relative = Path(variant) / 'cmd/xshard.o'
            cmd = command(Path('build') / relative, '-c src/cmd/xshard.cc ')
            cmd[cmd.index('-c') + 1] = str(folder / 'xshard.cc')
            output = folder / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            cmd[cmd.index('-o') + 1] = str(output)
            cmd += ['-Isrc/cmd']
            jobs.append((folder / (variant.replace('/', '-') + '.log'), cmd))
            if control == 'no-hold':
                relative = Path(variant) / 'cmd/blocking_debug.o'
                cmd = command(Path('build') / relative, '-c src/cmd/blocking_debug.cc ')
                cmd[cmd.index('-c') + 1] = str(folder / 'blocking_debug.cc')
                cmd[cmd.index('-o') + 1] = str(folder / relative)
                cmd += ['-Isrc/cmd']
                jobs.append((folder / (variant.replace('/', '-') + '-debug.log'), cmd))
    def compile_one(job):
        path, cmd = job
        with path.open('w') as log:
            subprocess.run(['taskset', '-c', '112-127', *cmd], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        return cmd
    with ThreadPoolExecutor(max_workers=4) as pool:
        commands = list(pool.map(compile_one, jobs))
    for folder in folders:
        for unit in ('aclkeys-wake-unit', 'aclkeys-wake-db0-unit'):
            cmd = command(Path('build') / unit, 'tests/aclkeys_wake_unit.cc')
            cmd = [str(folder / item.removeprefix('build/'))
                   if item in ('build/src/cmd/xshard.o', 'build/db0/src/cmd/xshard.o') or
                      (folder.name == 'no-hold' and item in ('build/src/cmd/blocking_debug.o',
                                                            'build/db0/src/cmd/blocking_debug.o')) else item
                   for item in cmd]
            cmd[cmd.index('-o') + 1] = str(folder / unit)
            compile_one((folder / (unit + '.log'), cmd))
            commands.append(cmd)
        (folder / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        print('built', folder, flush=True)


if __name__ == '__main__':
    main()
