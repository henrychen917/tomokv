#!/usr/bin/env python3
"""parkwake: one line per matrix row (tools/parkwake_matrix.py output), case-specific metric.

usage: parkwake_summary.py DIR/ARM [...]   -> prints a markdown table; --json writes ARM.json
"""
import json
from pathlib import Path
import sys


def metric(case, legs):
    out = []
    for leg in legs:
        db = leg.get('databases')
        if case == 'retry':
            forms = leg.get('forms', {})
            out.append(f"db{db}: " + ', '.join(f"{k} max {v['max_ms']} ms" + (f" ({v['misses']} miss)" if v['misses'] else '')
                                             + (f", esc {v['escalations']}" if 'escalations' in v else '')
                                             + (f", retries {v['retries']}" if 'retries' in v else '')
                                             for k, v in forms.items()))
        elif case == 'control':
            forms = leg.get('forms', {})
            out.append(f"db{db}: " + ', '.join(f"{k} max {v['max_ms']} ms" for k, v in forms.items()))
        elif case == 'epoch':
            v = leg.get('fd_release', {})
            out.append(f"db{db}: fd release max {v.get('max_ms')} ms, p50 {v.get('p50_ms')} ms, {v.get('misses')} miss")
        elif case == 'slotless':
            out.append(f"db{db}: slowest/round {leg.get('rounds_slowest_ms')} ms, notify_drop {leg.get('notify_drop')}")
        elif case == 'watchdog':
            out.append(f"long {leg.get('long_command_s')} s, SWAPDB {leg.get('swapdb_done_s')} s, exit {leg.get('server_exit')}")
        elif case == 'script':
            out.append(f"db{db}: lane-full {leg.get('lane_full_errors')}, ok {leg.get('replies_ok')}")
        elif case == 'swapdb':
            v = leg.get('swapdb', {})
            out.append(f"SWAPDB max {v.get('max_ms')} ms, p50 {v.get('p50_ms')} ms, {v.get('misses')} over deadline")
        if leg.get('reasons'):
            out[-1] += ' | ' + '; '.join(leg['reasons'])[:300]
    return ' / '.join(out)


def main():
    for arg in sys.argv[1:]:
        if arg == '--json':
            continue
        rows = json.loads((Path(arg) / 'summary.json').read_text())
        print(f'### {Path(arg).name}\n')
        print('| Row | Verdict | Witness |')
        print('|---|---|---|')
        compact = []
        for row in rows:
            name = f"{row['case']}-{row['mode']}-{row['engine']}"
            verdict = 'PASS' if row['rc'] == 0 else 'FAIL'
            text = metric(row['case'], row['legs'])
            print(f'| {name} | {verdict} | {text} |')
            compact.append(dict(row=name, verdict=verdict, witness=text))
        print()
        if '--json' in sys.argv:
            (Path(arg).parent / f'{Path(arg).name}.json').write_text(json.dumps(compact, indent=1) + '\n')


if __name__ == '__main__':
    main()
