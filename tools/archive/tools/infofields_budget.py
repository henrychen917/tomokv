#!/usr/bin/env python3
"""Offline, TU-local compiler-budget trials; never executes a server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from ccfix4_budget import inventory, compare
from ccfix_audit import audit

_base_target = audit.Elf.target
def constant_target(self, symbol, addend, kind):
    if symbol["name"].startswith(".LC") and 0 < symbol["sec"] < len(self.sections):
        sec = self.sections[symbol["sec"]]
        if sec[2] & 0x10 and not sec[2] & 0x20 and sec[9]:
            offset = symbol["value"] + addend + (4 if kind in (2, 4, 9, 41, 42) else 0)
            return ("constant-entry", self.section_data(symbol["sec"])[offset:offset + sec[9]].hex())
    return _base_target(self, symbol, addend, kind)
audit.Elf.target = constant_target

ROOT = Path(__file__).resolve().parents[1]
COLD = re.compile(r'::(?:info_|command_bind_server\(|command_config_resetstat\(|'
                  r'\(anonymous namespace\)::cmd_(?:info|config)\(|'
                  r'IoLoop::climon_monitor_feed\(|snapshot_last_bgsave_ok\(|record_bgsave_failure\(|'
                  r'SnapshotManager::(?:abort_file|complete_file_success|init|start)\()')


def selected(path):
    result = inventory(path)
    # Preserve every emitted body outside the explicitly edited cold functions.
    for row in result.values():
        row['hot'] = not COLD.search(row['name'])
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tu')
    p.add_argument('values', nargs='+', type=int)
    p.add_argument('--db0', action='store_true')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--growth', type=int, default=0)
    a = p.parse_args()
    rel = ('db0/' if a.db0 else '') + a.tu.removesuffix('.cc') + '.o'
    old = selected(ROOT / 'build/infofields/PRE' / rel)
    out = ROOT / 'build/infofields/budgets' / (Path(a.tu).stem + ('-db0' if a.db0 else ''))
    out.mkdir(exist_ok=True, parents=True)
    def trial(value):
        target = out / f'{value}-g{a.growth}.o'
        cmd = ['taskset', '-c', '0-15', 'g++', '-std=c++20', '-O2', '-g0', '-Wall', '-Wextra',
               '-march=native', '-pthread', '-DTOMO_JEMALLOC', '-I.',
               '--param', f'inline-unit-growth={a.growth}', '--param', f'large-unit-insns={value}']
        if a.db0: cmd += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        cmd += ['-c', a.tu, '-o', str(target)]
        with (out / f'{value}-g{a.growth}.log').open('w') as log:
            subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        report = dict(command=cmd, value=value, **compare(old, selected(target)))
        (out / f'{value}-g{a.growth}.json').write_text(json.dumps(report, indent=2) + '\n')
        print(value, report['hot_changed'], report['hot_differing_bytes'], flush=True)
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        list(pool.map(trial, a.values))


if __name__ == '__main__':
    main()
