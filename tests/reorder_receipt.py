#!/usr/bin/env python3
"""Current-tree FIFO behaviour twin and strict off-path instruction receipt.

This proves the candidate's ordinary bodies are identical in its FIFO twin,
including missing-symbol and operand-mutation controls. It does not re-create
the historical pre-R7 binary or prove the cost of introducing R7 from scratch.
No server is executed. PAD kind A: FIFO behaviour, candidate size and layout.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

import reorder_noop as audit
import r7shadow_noop
from r7shadow_pad import twin


def controls(binary, output):
    # These are disposable parsed instruction images, never executable mutants.
    post = copy.copy(binary)
    post.groups = copy.deepcopy(binary.groups)
    missing = [name for name in post.groups if '::flush_ready<' in name]
    assert missing, 'missing-symbol control must remove real symbols'
    for name in missing: del post.groups[name]
    try:
        audit.compare(binary, post, output)
    except ValueError as error:
        assert 'missing policy symbol' in str(error), str(error)
    else:
        raise AssertionError('missing-symbol negative control passed')
    post.groups = copy.deepcopy(binary.groups)
    name = next(n for n in post.groups if audit.category(n) == 'commands')
    post.groups[name][0]['encodings'][0] += ' ff'
    rows = audit.compare(binary, post, output)
    assert any(not row['equal'] and row['name'] == name for row in rows), 'changed-opcode negative control passed'
    print('PASS missing policy symbol and changed opcode fail strict identity')


def engagement(binary, output):
    output.mkdir(parents=True, exist_ok=True)
    def run(path, expected):
        result = subprocess.run([str(path.resolve()), expected, 'shadow'],
                                text=True, capture_output=True, timeout=120)
        (output / f'{path.name}-{expected}.log').write_text(result.stdout + result.stderr)
        return result
    result = run(binary, 'on')
    assert result.returncode == 0, result.stdout + result.stderr
    pad = output / 'fifo-twin'
    receipt = twin(binary, pad, scope='fifo')
    (output / 'twin.json').write_text(json.dumps(receipt, indent=2) + '\n')
    result = run(pad, 'off')
    assert result.returncode == 0, result.stdout + result.stderr
    result = run(pad, 'on')
    assert result.returncode == 1 and 'binary capability differs from expected arm' in result.stderr, result
    print(f'PASS {binary}: production shadow, FIFO control, disabled capability rejected')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--engagement', action='store_true')
    args = parser.parse_args()
    if args.engagement:
        engagement(args.binary, args.output)
        raise SystemExit(0)
    args.output.mkdir(parents=True, exist_ok=True)
    pad = args.output / 'fifo-twin'
    receipt = twin(args.binary, pad, scope='fifo')
    (args.output / 'twin.json').write_text(json.dumps(receipt, indent=2) + '\n')
    subprocess.run([sys.executable, str(Path(__file__).with_name('r7shadow_noop.py')),
                    str(pad), str(args.binary), str(args.output / 'identity'),
                    '--inventory', 'wbrule'], check=True)
    negative = args.output / 'negative'
    negative.mkdir(exist_ok=True)
    binary = audit.Binary(args.binary, negative, literal_pools=True)
    r7shadow_noop.off_roles(binary)
    controls(binary, negative)
