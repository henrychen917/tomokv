#!/usr/bin/env python3
"""wave3 (from docs/wave2/tools/linked_attribution.py): which changed object bodies reach the linked
binary. Re-runs each build's exact link command (from its make log) with -Wl,-Map into
build/wave3/maps (the build outputs are not touched), checks that the relinked binary equals the
shipped one in every loadable section, then, for every body attribute.py lists as changed, reports
whether its object's copy is linked or discarded (a COMDAT group whose kept copy is another
object's). Never runs a binary. usage: linked_attribution.py <attr.json> <post-build.log> <out.json>"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

WT = Path('/home/user/Projects/cx-wave3')
MAPS = WT / 'build/wave3/maps'


def link(tag, cwd, log):
    line = next(l for l in log.read_text().splitlines()
                if l.startswith('g++ ') and ' -o build/tomokv ' in l)
    argv = shlex.split(line)
    out = MAPS / f'{tag}-tomokv'
    argv[argv.index('-o') + 1] = str(out)
    argv.append(f'-Wl,-Map={MAPS / (tag + ".map")}')
    MAPS.mkdir(parents=True, exist_ok=True)
    subprocess.run(['taskset', '-c', os.environ.get('LINK_CPUS', '80-95'), *argv], cwd=cwd, check=True)
    same = subprocess.run([sys.executable, str(WT / 'docs/deadswitch/linked_bytes.py'), str(cwd / 'build/tomokv'),
                           str(out), str(MAPS / f'{tag}-relink.json')], capture_output=True, text=True)
    return MAPS / f'{tag}.map', same.returncode == 0


def discarded(mapfile):
    """{(object, section)} listed under 'Discarded input sections'."""
    text = mapfile.read_text(errors='replace')
    start = text.index('Discarded input sections')
    end = text.index('Memory Configuration', start)
    rows, pending = set(), None
    for line in text[start:end].splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split()
        if line.startswith(' ') and not line.startswith('  ') and len(parts) >= 4:
            rows.add((parts[3], parts[0]))
            pending = None
        elif line.startswith(' ') and len(parts) == 1:
            pending = parts[0]
        elif pending and len(parts) >= 3:
            rows.add((parts[2], pending))
            pending = None
    return rows


def main():
    attr = json.load(open(sys.argv[1]))
    builds = {'pre': (WT / 'build/wave3/refs/pre-src', WT / 'build/wave3/refs/pre-build.log'),
              'post': (WT, Path(sys.argv[2]).resolve())}
    maps, relink_equal = {}, {}
    for tag, (cwd, log) in builds.items():
        maps[tag], relink_equal[tag] = link(tag, cwd, log)
    gone = {tag: discarded(maps[tag]) for tag in maps}
    result = []
    for r in attr:
        for x in r['rows']:
            obj = 'build/' + x['object']
            symbol = re.sub(r'\.(?:cold|isra\.\d+|part\.\d+|constprop\.\d+)+$', '', x['symbol'])
            sections = {f'.text.{symbol}', f'.text.unlikely.{symbol}', f'.text.startup.{symbol}'}
            state = {}
            for tag in ('pre', 'post'):
                hit = [s for o, s in gone[tag] if o == obj and s in sections]
                state[tag] = 'discarded (another object\'s COMDAT copy is linked)' if hit else 'linked'
            if x['kind'] == 'added':
                state['pre'] = 'absent'
            if x['kind'] == 'removed':
                state['post'] = 'absent'
            result.append(dict(object=x['object'], name=x['name'], cls=x['cls'],
                               lanes=x['lanes_changed'], hot=x['hot'], pre=state['pre'], post=state['post']))
    reach = [y for y in result if y['post'] == 'linked']
    summary = dict(changed_object_bodies=len(result), reaching_binary=len(reach),
                   discarded_copies=sum(y['post'].startswith('discarded') for y in result),
                   removed=sum(y['post'] == 'absent' for y in result),
                   reaching_by_class={c: sum(y['cls'] == c for y in reach) for c in 'ABCD'},
                   hot_reaching=sum(y['hot'] for y in reach),
                   relinked_equals_shipped=relink_equal,
                   maps={tag: str(maps[tag].relative_to(WT)) for tag in maps})
    Path(sys.argv[3]).write_text(json.dumps(dict(summary=summary, bodies=result), indent=1) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
