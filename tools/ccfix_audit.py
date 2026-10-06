#!/usr/bin/env python3
"""Offline PRE/POST function-byte inventory. No listeners or workloads are started."""
import argparse
import gzip
import inspect
import json
from pathlib import Path
import re
import subprocess
import textwrap
import lbstall_artifacts as audit

# Match gt13split's extension for TLS offsets; preserve target identities and all opcodes.
source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
assert source.count('24: 8,') == 1
scope = vars(audit).copy()
exec(source.replace('24: 8,', '23: 4, 24: 8,'), scope)
audit.Elf.canonical = scope['canonical']

# Object files also encode local static data as section+offset relocations. Resolve those
# to the named object and its internal byte offset, as the existing checker does for code.
# This does not erase member offsets: moving a load within StatBaseline still fails.
original_target = audit.Elf.target

def data_target(self, symbol, addend, kind):
    sec = symbol['sec']
    if symbol['info'] & 15 == 3 and 0 < sec < len(self.sections) and not self.sections[sec][2] & 4:
        offset = symbol['value'] + addend + (4 if kind in (2, 4, 9, 41, 42) else 0)
        for obj in self.symbols:
            if obj['info'] & 15 == 1 and obj['name'] and obj['sec'] == sec and \
                    obj['value'] <= offset < obj['value'] + obj['size']:
                if obj['name'].startswith('CSWTCH.'):
                    data = self.section_data(sec)[obj['value']:obj['value'] + obj['size']]
                    assert not any(obj['value'] <= r[0] < obj['value'] + obj['size']
                                   for r in self.relocs.get(sec, []))
                    return ('constant-object', data.hex(), offset - obj['value'])
                return ('object', obj['name'], offset - obj['value'])
    return original_target(self, symbol, addend, kind)

audit.Elf.target = data_target


def error_callee_twin(canonical):
    """Only the owner's admitted error sink relocation; never mask instructions."""
    body, targets = canonical
    def target_twin(value):
        if isinstance(value, str):
            return value.replace('2Op4Sink12append_errorEPKcm', '2Op4Sink6appendEPKcm')
        if isinstance(value, tuple):
            return tuple(target_twin(item) for item in value)
        return value
    return body, [target_twin(target) for target in targets]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--error-callees', action='store_true',
                        help='admit append -> append_error relocation on error-only producers')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    objects = list((args.pre / 'src').rglob('*.o')) + list((args.pre / 'db0/src').rglob('*.o'))
    for path in sorted(objects):
        rel = path.relative_to(args.pre)
        other = args.post / rel
        assert other.exists(), other
        before, after = audit.Elf(path), audit.Elf(other)
        old, new = before.functions(), after.functions()
        names = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
        for symbol, name in zip(names, labels):
            a, b = old.get(symbol), new.get(symbol)
            equal = bool(a and b and before.canonical(a) == after.canonical(b))
            error_only = bool(a and b and not equal and
                              error_callee_twin(before.canonical(a)) ==
                              error_callee_twin(after.canonical(b)))
            rows.append(dict(object=str(rel), symbol=symbol, name=name, equal=equal,
                             error_callee_only=error_only,
                             raw_equal=bool(a and b and before.body(a) == after.body(b)),
                             pre_size=a['size'] if a else 0, post_size=b['size'] if b else 0))
        print(str(rel), len(names), 'bodies', flush=True)
    with gzip.open(args.output / 'bodies.json.gz', 'wt') as f:
        json.dump(rows, f, indent=2)
    changed = [r for r in rows if not r['equal']]
    for row in changed:
        row['classification'] = 'error-branch callee only' if row['error_callee_only'] else 'other'
    (args.output / 'changed-bodies.json').write_text(json.dumps(changed, indent=2) + '\n')
    handlers = [r for r in rows if re.search(r'::cmd_\w+(?:<|\()', r['name'])]
    hot = [r for r in rows if audit.HOT.search(r['name']) or
           re.search(r'ExLoopT<.*>::run\(', r['name'])]
    report = dict(total=len(rows), equal=sum(r['equal'] for r in rows), changed=len(changed),
                  handlers=len(handlers), handlers_equal=sum(r['equal'] for r in handlers),
                  hot=len(hot), hot_equal=sum(r['equal'] for r in hot),
                  changed_handlers=[r for r in handlers if not r['equal']],
                  changed_hot=[r for r in hot if not r['equal']])
    allowed = lambda r: r['equal'] or (args.error_callees and r['error_callee_only'])
    report['hot_nonerror_equal'] = sum(allowed(r) for r in hot)
    report['handlers_nonerror_equal'] = sum(allowed(r) for r in handlers)
    report['other_handlers'] = [r for r in handlers if not allowed(r)]
    report['other_hot'] = [r for r in hot if not allowed(r)]
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if not isinstance(v,list)}))
    assert not report['other_hot'], 'ordinary hot-path bytes changed'
    assert all(re.search(r'::cmd_(?:config|info|acl)\(', r['name'])
               for r in report['other_handlers']), 'ordinary command bytes changed'


if __name__ == '__main__':
    main()
