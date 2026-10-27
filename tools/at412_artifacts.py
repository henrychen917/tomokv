#!/usr/bin/env python3
"""AT4.12 offline identity, bounded instruction counts and PAD-A artifacts.

Reuses the execindex lane's instruments with recorded path/CPU substitutions.
The scope fixture links the saved PRE objects and current production objects,
including both physical namespaces. Only control_smoke starts correctness
servers; none of these modes runs a load generator or measures throughput.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/at412c'
BUILD = ROOT / 'build/at412'


def inherited(tool, args, scripts=False):
    original = ROOT / ('tools/execindex_'+tool+'.py')
    source = original.read_text()
    source = source.replace('execindex', 'at412')
    source = source.replace('docs/at412', 'docs/at412c')
    if tool == 'scope':
        # A rebuilt probe invalidates its earlier traces. The inherited tool's
        # receipt was overwritten at build time and did not bind cached counts.
        source = source.replace('if output.exists() and "COUNT " in log_text:',
            'if output.exists() and "COUNT " in log_text and '
            'json.loads(output.read_text()).get("probe_sha256") == '
            'hashlib.sha256(binary.read_bytes()).hexdigest():')
        source = source.replace('json.dump(dict(total=sum(counts.values()),',
            'json.dump(dict(probe_sha256={hashlib.sha256(binary.read_bytes()).hexdigest()!r},'
            'total=sum(counts.values()),')
    # Instruction traces run at nice 19 on 56-63, away from the gate's server cores 48-55.
    cpus = '56-63' if tool == 'scope' else '48-55' if tool == 'control_smoke' else '48-63'
    source = source.replace('96-103', cpus).replace('96-111', cpus)
    if tool == 'control_smoke':
        source = source.replace('PORT=46890', 'PORT=20290')  # this lane's port range
    if tool == 'scope' and scripts:
        source = source.replace('docs/at412c/instructions', 'docs/at412c/script-instructions')
        source = source.replace('("GET", "SET", "INCR", "MGET", "MSET")', '("EVAL", "EVAL-ADMIT")')
        source = source.replace('for batch in (1, 32)', 'for batch in (1,)')
        source = source.replace('command == "MSET"', 'command.startswith("EVAL")')
        # Follow fixture callbacks so later script waves and the Final release
        # are visited, while still counting production instructions only.
        source = source.replace('if prefix in name and "CoreConcurrencyTest::" not in name',
                                'if prefix in name')
        source = source.replace(' if fn:\n  counts[fn[3]]+=1',
                                ' if fn and "CoreConcurrencyTest::" not in fn[3]:\n  counts[fn[3]]+=1')
    saved = BUILD / ('instrument-'+tool+('-scripts' if scripts else '')+'.py')
    saved.write_text(source)
    (OUT / (saved.stem+'.json')).write_text(json.dumps(dict(
        source=str(original), source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        derived=str(saved), derived_sha256=hashlib.sha256(saved.read_bytes()).hexdigest(),
        cpu=cpus, substitutions=['execindex -> at412', '96-103 -> ' + cpus, '96-111 -> ' + cpus],
        script_scopes=scripts), indent=2)+'\n')
    sys.argv = [str(saved), *args]
    # Keep the instrument's ROOT discovery anchored at the actual tools dir.
    scope = {'__name__': 'at412_instrument', '__file__': str(ROOT / ('tools/at412_'+tool+'.py'))}
    exec(compile(source, str(saved), 'exec'), scope)
    scope['main']()


def identity():
    dest = OUT / 'identity'; dest.mkdir(exist_ok=True)
    pre = BUILD / 'pre'; post = ROOT / 'build'
    with (dest/'ccfix.log').open('w') as log:
        ccfix = subprocess.run([sys.executable, str(ROOT/'tools/ccfix_audit.py'),
                                str(pre), str(post), str(dest/'ccfix')], stdout=log, stderr=subprocess.STDOUT)
    # ccfix asserts that no ordinary hot body changed. The design's only hot edit is the cold
    # resume arm (io_loop.h / reorder.cc, §3.6), compiled into every flush_ready/r7_flush_ready
    # instantiation; accept exactly that, and fail on any other hot or handler body.
    report = json.loads((dest/'ccfix'/'summary.json').read_text())
    other = [r['name'] for r in report['other_hot']]
    assert ccfix.returncode in (0, 1) and all(re.search(r'IoLoop::(?:r7_)?flush_ready<', n) for n in other), other
    assert all(re.search(r'::cmd_(?:info|debug_impl)\(', r['name']) for r in report['other_handlers'])
    # ccfix's canonicalization preserves member offsets while resolving TLS
    # and named static-data relocations. Use the same extension for the hot list.
    import ccfix_audit
    import lbstall_artifacts as audit
    audit.HOT = re.compile(audit.HOT.pattern +
        r'|cmd_incr(?:\(|<)|cmd_xshard_only|xshard_(?:prepare|execute|complete|retire|flush_commits)|'
        r'assemble_final|atomic_has_records|script_window_resume')
    with (dest/'hot.log').open('w') as log:
        original = sys.stdout
        try:
            sys.stdout = log
            equal = audit.compare(pre, post, dest/'hot-bodies.json')
        finally:
            sys.stdout = original
    with (dest/'linked-bytes.log').open('w') as log:
        result = subprocess.run([sys.executable, str(ROOT/'docs/deadswitch/linked_bytes.py'),
            str(pre/'tomokv'), str(post/'tomokv'), str(dest/'linked-bytes.json')],
            stdout=log, stderr=subprocess.STDOUT)
    assert result.returncode in (0, 1) and (dest/'linked-bytes.json').exists()
    rows = json.loads((dest/'hot-bodies.json').read_text())
    handlers = [r for r in rows if re.search(r'cmd_(get|set|incr|mget|mset)(?:\(|<)|cmd_xshard_only', r['name'])]
    summary = dict(hot_bodies=len(rows), hot_equal=sum(r['relocation_equal'] for r in rows),
                   all_hot_equal=equal, command_bodies=len(handlers),
                   command_equal=sum(r['relocation_equal'] for r in handlers),
                   linked_sections_equal=result.returncode == 0)
    (dest/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['identity','scope','script-scope','pad','budget','control_smoke'])
    args, rest = parser.parse_known_args()
    OUT.mkdir(parents=True, exist_ok=True); BUILD.mkdir(parents=True, exist_ok=True)
    if args.mode == 'identity':
        assert not rest
        identity()
    else:
        inherited('scope' if args.mode == 'script-scope' else args.mode,
                  rest, scripts=args.mode == 'script-scope')


if __name__ == '__main__':
    main()
