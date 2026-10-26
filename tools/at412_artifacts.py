#!/usr/bin/env python3
"""AT4.12 offline identity, bounded instruction counts and PAD-A artifacts.

Reuses the execindex lane's instruments with recorded path/CPU substitutions.
No server or load generator is started. The scope fixture links the saved PRE
objects and current production objects, including both physical namespaces.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/at412'
BUILD = ROOT / 'build/at412'


def inherited(tool, args, scripts=False):
    original = ROOT / ('tools/execindex_'+tool+'.py')
    source = original.read_text()
    source = source.replace('execindex', 'at412')
    # Instruction traces run at nice 19 on 56-63, away from the gate's server cores 48-55.
    cpus = '56-63' if tool == 'scope' else '48-63'  # the probe needs 8 CPUs in its affinity
    source = source.replace('96-103', cpus).replace('96-111', cpus)
    if tool == 'control_smoke':
        source = source.replace('PORT=46890', 'PORT=20290')  # this lane's port range
    if tool == 'scope' and scripts:
        source = source.replace('docs/at412/instructions', 'docs/at412/script-instructions')
        source = source.replace('("GET", "SET", "INCR", "MGET", "MSET")', '("EVAL", "EVAL-ADMIT")')
        source = source.replace('for batch in (1, 32)', 'for batch in (1,)')
        source = source.replace('command == "MSET"', 'command.startswith("EVAL")')
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
        subprocess.run([sys.executable, str(ROOT/'tools/ccfix_audit.py'),
                        str(pre), str(post), str(dest/'ccfix')], stdout=log, stderr=subprocess.STDOUT, check=True)
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
