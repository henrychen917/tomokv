#!/usr/bin/env python3
"""Compile/byte-audit only the two changed TUs; never starts a listener or workload."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from ccfix4_budget import inventory, compare

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = re.compile(r'::(?:blocking_(?:task_done|request_move|execute|scatter_retire|resume_move_impl|debug_xread_hold|dispatch_selected|fail_registration_oom)|BlockingRegistry::service|debug_xread_registration_|cmd_debug(?:_impl)?\()')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tu', choices=('server', 'xshard'))
    p.add_argument('variant', choices=('src', 'db0'))
    p.add_argument('values', nargs='+', type=int)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--dump', action='store_true')
    p.add_argument('--auto', type=int, help='changed-TU max-inline-insns-auto budget')
    args = p.parse_args()
    stem = 't_server' if args.tu == 'server' else 'xshard'
    relative = Path('src/cmd' if args.variant == 'src' else 'db0/src/cmd') / (stem + '.o')
    pre = ROOT / 'build/aclkeys/PRE' / relative
    old = inventory(pre)
    for row in old.values():
        row['hot'] = not bool(ALLOWED.search(row['name']))
    original = next(shlex.split(line) for line in subprocess.check_output(
        ['make', '-n', '-B', str(Path('build') / relative)], cwd=ROOT, text=True).splitlines()
        if line.startswith('g++ ') and f'-c src/cmd/{stem}.cc ' in line)
    folder = ROOT / 'build/aclkeys3/budgets' / (args.tu + '-' + args.variant +
             (f'-auto{args.auto}' if args.auto is not None else ''))
    folder.mkdir(parents=True, exist_ok=True)

    def trial(value):
        target = folder / f'{value}.o'
        command = [f'large-unit-insns={value}' if token.startswith('large-unit-insns=')
                   else '-g0' if token == '-g' else token for token in original]
        command[command.index('-o') + 1] = str(target)
        if args.auto is not None:
            command = [f'max-inline-insns-auto={args.auto}' if token.startswith('max-inline-insns-auto=')
                       else token for token in command]
            if not any(token.startswith('max-inline-insns-auto=') for token in command):
                command += ['--param', f'max-inline-insns-auto={args.auto}']
        if args.dump:
            command.append('-fdump-ipa-inline-details=' + str(folder / f'{value}.inline'))
        with (folder / f'{value}.log').open('w') as log:
            subprocess.run(['taskset', '-c', '112-127', *command], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        new = inventory(target)
        for row in new.values():
            row['hot'] = not bool(ALLOWED.search(row['name']))
        result = dict(value=value, pre=str(pre), command=command,
                      sha256=hashlib.sha256(target.read_bytes()).hexdigest(), **compare(old, new))
        (folder / f'{value}.json').write_text(json.dumps(result, indent=2) + '\n')
        print(args.tu, args.variant, value, 'outside_path', result['hot_changed'],
              'bytes', result['hot_differing_bytes'], flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(trial, args.values))
    best = min(results, key=lambda row: (row['hot_changed'], row['hot_differing_bytes']))
    print('BEST', args.tu, args.variant, best['value'], best['hot_changed'], flush=True)


if __name__ == '__main__':
    main()
