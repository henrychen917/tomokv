#!/usr/bin/env python3
"""Count executed complete GET/SET instructions in every production parser body.

Each GDB run executes only copied, already-disassembled parser instructions in a
serverless fixture. Cold clones are included in the static inventory, not entered
by a complete positive-length GET/SET. The caller/dispatched command is excluded.
"""
import argparse
import gzip
import json
from pathlib import Path
import subprocess

GDB = '''set pagination off
set confirm off
set startup-with-shell off
break trace_ready
run
python
import gdb, json
start = int(gdb.parse_and_eval('(unsigned long)trace_entry'))
end = int(gdb.parse_and_eval('(unsigned long)trace_end'))
for _ in range(300):
    if int(gdb.parse_and_eval('$pc')) == start: break
    gdb.execute('stepi', to_string=True)
else: raise RuntimeError('parser entry not reached')
count = stores = 0
while True:
    pc = int(gdb.parse_and_eval('$pc'))
    if not start <= pc < end: raise RuntimeError('complete path left parser body')
    asm = gdb.selected_frame().architecture().disassemble(pc, count=1)[0]['asm']
    count += 1
    if asm.startswith('push') or (asm.startswith(('mov', 'vmov')) and '(' in asm.rsplit(',', 1)[-1]): stores += 1
    if count > 10000: raise RuntimeError('instruction limit')
    gdb.execute('stepi', to_string=True)
    if asm.startswith('ret'): break
print('TRACE=' + json.dumps(dict(instructions=count, stores=stores)))
end
continue
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inventory', type=Path)
    ap.add_argument('--post', action='store_true')
    args = ap.parse_args()
    content = args.inventory.read_bytes()
    data = json.loads(gzip.decompress(content) if args.inventory.suffix == '.gz' else content)
    script = Path('build/respresume-trace.gdb')
    script.write_text(GDB)
    rows = []
    for r in data['rows']:
        if '::resp_parse_t<' not in r['name'] or '.cold' in r['name']:
            continue
        for command in ('GET', 'SET'):
            # Both namespaces have identical locked Op/Slice layouts.
            argv = ['gdb', '-q', '-batch', '-x', str(script), '--args',
                    'build/respresume-trace', data['binary'], r['address'], str(r['bytes']),
                    str(int('resp_parse_t<true' in r['name'])), str(int(args.post)), command]
            run = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            path = args.inventory.parent / f'trace-{r["address"]}-{command}.log'
            path = path.with_suffix('.log.gz')
            path.write_bytes(gzip.compress(run.stdout.encode(), mtime=0))
            trace = [line[6:] for line in run.stdout.splitlines() if line.startswith('TRACE=')]
            assert run.returncode == 0 and len(trace) == 1 and 'validated complete frame' in run.stdout, path
            rows.append(dict(address=r['address'], symbol=r['name'], command=command, **json.loads(trace[0])))
    (args.inventory.parent / 'fast-path.json').write_text(json.dumps(rows, indent=2) + '\n')
    with (args.inventory.parent / 'fast-path.tsv').open('w') as f:
        f.write('address\tcommand\texecuted_instructions\tstores\tsymbol\n')
        for r in rows:
            f.write('\t'.join(str(r[k]) for k in ('address', 'command', 'instructions', 'stores', 'symbol')) + '\n')
    print('traced', len(rows), 'complete-frame paths')


if __name__ == '__main__': main()
