#!/usr/bin/env python3
"""Bind counted native bodies (including visited assembly stubs) to production."""
import argparse, bisect, gzip, hashlib, json, os, re, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import wave11
from wave11_counts import symbols
from wave11_normalize import install
identity = wave11.references()
install(identity.audit)
identity.OUT = ROOT / 'build/wave11/identity-wave11'
DOC = ROOT / 'docs/wave11'


def assembly(path):
    syms = symbols(path)
    names = {s[2]: identity.audit.canonical(s[3]) for s in syms}
    text = subprocess.check_output(['objdump', '-d', '-w', '-j', '.rlfence', str(path)], text=True)
    lines = []
    for line in text.splitlines():
        if m := identity.audit.INSTRUCTION.match(line):
            lines.append((int(m[1], 16), m[2].split(), m[3]))
    if not lines:
        return None, {}
    start = lines[0][0]
    size = lines[-1][0] + len(lines[-1][1]) - start
    return start, {pc-start: [identity.audit.normalize_asm(asm, start, size, names),
                            identity.audit.normalized_encoding(raw, asm, pc, start, size)]
                   for pc, raw, asm in lines}


def main():
    assert os.sched_getaffinity(0) <= set(range(64, 96))
    p = argparse.ArgumentParser()
    p.add_argument('label'); p.add_argument('server', type=Path)
    p.add_argument('--domain', choices=('complete','lua'), default='complete')
    p.add_argument('--receipt', help='Distinct receipt name for another frozen reference')
    a = p.parse_args()
    server = identity.inventory(a.server)
    _, server_asm = assembly(a.server)
    rows = []
    for ns in ('normal', 'db0'):
        binary = ROOT / f'build/wave11/counts/scopes/{a.label}-{ns}/probe'
        probe = identity.inventory(binary)
        by_address = {int(b['address'], 16): (name, b)
                      for name, bodies in probe['groups'].items() for b in bodies}
        addresses = sorted(by_address)
        asm_start, probe_asm = assembly(binary)
        used, asm_used = {}, {}
        traces = list((DOC / 'instructions' / a.label / a.domain).glob(ns+'-*.json'))
        assert traces, (a.label, ns, 'no traces')
        for file in traces:
            row = json.loads(file.read_text())
            assert row['probe_sha256'] == probe['sha256'], file
            with gzip.open(str(file)+'.sites.gz', 'rt') as f:
                sites = json.load(f)['sites']
            for addr, count in sites.items():
                pc = int(addr, 16)
                if asm_start is not None and pc-asm_start in probe_asm:
                    asm_used[pc-asm_start] = asm_used.get(pc-asm_start, 0)+count
                    continue
                at = addresses[bisect.bisect_right(addresses, pc)-1]
                name, body = by_address[at]
                assert at <= pc < at+body['size'], (hex(pc), name)
                used[at] = used.get(at, 0)+count
        for at, count in sorted(used.items()):
            name, body = by_address[at]
            matches = [b for b in server['groups'].get(name, []) if b['digest'] == body['digest']]
            rows.append(dict(namespace=ns, name=name, count=count, probe=body,
                             matches=matches, passed=bool(matches)))
        for offset, count in sorted(asm_used.items()):
            rows.append(dict(namespace=ns, name='[asm .rlfence]', offset=hex(offset), count=count,
                             probe=probe_asm[offset], server=server_asm.get(offset),
                             passed=probe_asm[offset] == server_asm.get(offset)))
    result = dict(label=a.label, domain=a.domain, server_sha256=server['sha256'], bodies=rows,
                  passed=all(r['passed'] for r in rows))
    (DOC / ('binding-'+(a.receipt or a.label)+('' if a.domain=='complete' else '-'+a.domain)+'.json')).write_text(json.dumps(result, indent=2)+'\n')
    print(a.label, len(rows), 'bodies/stub instructions;', sum(not r['passed'] for r in rows), 'mismatches', flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
