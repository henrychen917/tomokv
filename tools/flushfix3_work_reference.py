#!/usr/bin/env python3
"""Falsify the work envelope with F2's actual chain walk, bounded before excess.

The throwaway serverless image stops at envelope + 1 visited entries. Full F2
counts are also computed exactly for this disjoint-key fixture; trillion-entry
walks are deliberately not executed. No production object is overwritten.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import source_tokens as cpp
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/flushfix3/work-reference'
F2 = 'a42e527b0'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare-only', action='store_true')
    p.add_argument('--namespace', choices=('normal', 'db0'), required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cores', default='0-15', help='caller-owned build/test CPU allocation')
    a = p.parse_args()
    allowed = set()
    for part in a.cores.split(','):
        ends = list(map(int, part.split('-')))
        allowed.update(range(ends[0], ends[-1] + 1))
    assert allowed and os.sched_getaffinity(0) <= allowed
    BUILD.mkdir(parents=True, exist_ok=True)
    a.output.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'show', F2 + ':src/store/flush.cc'], text=True)
    begin = original.index('void FlatStore::atomic_flush_erase(')
    end = original.index('\nuint64_t FlatStore::atomic_flush_resolved_size', begin)
    body = original[begin:end].replace('void FlatStore::atomic_flush_erase(',
                                       'bool FlatStore::atomic_flush_erase(', 1)
    opening = body.index('{') + 1
    body = body[:opening] + '''
    uint64_t work = 0, occurrences = 0;
    for (auto* e = range.next; e; e = e->next) occurrences += e->count;
    const uint64_t limit = 96 * (capacity() + occurrences);
    auto visit = [&] {
        if (++work > limit) {
            atomic_flush_counters.slow_work.fetch_add(work);
            throw std::runtime_error("F2 reference exceeds linear envelope");
        }
    };
''' + body[opening:]
    body = body.replace('for (auto* e = range.next; e; e = e->next) {',
                        'for (auto* e = range.next; e; e = e->next) { visit();')
    body = body.replace('for (uint32_t slot = 0; slot < cap_[table]; ++slot) {',
                        'for (uint32_t slot = 0; slot < cap_[table]; ++slot) { visit();')
    body = body.replace('for (uint32_t i = 0; i < e->count; ++i) {',
                        'for (uint32_t i = 0; i < e->count; ++i) { visit();')
    at = body.rfind('}')
    body = body[:at] + '    atomic_flush_counters.slow_work.fetch_add(work);\n    return true;\n' + body[at:]
    current = cpp.read(ROOT / 'src/store/flush.cc')
    begin, _, end = cpp.function_span(current, 'atomic_flush_erase')
    source = '#include <stdexcept>\n' + current[:begin] + body + current[end:]
    source = source.replace('#include "flatstore.h"', '#include "src/store/flatstore.h"')
    source = source.replace('#include "../core/signal.h"', '#include "src/core/signal.h"')
    generated = BUILD / ('reference-' + a.namespace + '.cc')
    generated.write_text(source)
    if a.prepare_only:
        print('source reference prepared:', generated)
        return
    target = 'build/flushfix3-' + ('db0-' if a.namespace == 'db0' else '') + 'unit'
    recipe = subprocess.check_output(['make', '-f', 'Makefile', '-f', 'tools/flushfix3.mk',
        '-n', '-W', 'tests/flushfix3_unit.cc', target], cwd=ROOT, text=True)
    commands = [shlex.split(line) for line in recipe.splitlines() if line.startswith('g++ ')]
    compile_command = next(c for c in commands if '-c' in c and 'tests/flushfix3_unit.cc' in c)
    link_command = next(c for c in commands if '-o' in c and c[c.index('-o') + 1] == target)
    old_object = compile_command[compile_command.index('-o') + 1]
    obj = BUILD / (a.namespace + '.o')
    binary = BUILD / (a.namespace + '-unit')
    compile_command[compile_command.index('-o') + 1] = str(obj)
    compile_command.append('-DTOMO_FLUSHFIX3_SOURCE="' + str(generated) + '"')
    link_command = [str(obj) if item == old_object else item for item in link_command]
    link_command[link_command.index('-o') + 1] = str(binary)
    with (a.output / 'build.log').open('w') as log:
        for command in (compile_command, link_command):
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    rows = []
    for later in (1000, 10000, 100000, 1000000):
        command = [str(binary), str(later)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
        output = result.stdout + result.stderr
        (a.output / f'P{later}.log').write_text(output)
        match = re.search(r'WORK slots=(\d+) residents=(\d+) P=(\d+) visits=(\d+) completed=0', output)
        assert result.returncode == 1 and match and 'F2 reference exceeds linear envelope' in output, output
        slots, residents, observed_p, visits = map(int, match.groups())
        assert observed_p == later and visits == 96 * (slots + later) + 1
        rows.append(dict(command=command, exit=result.returncode, slots=slots, residents=residents,
            P=later, visited_before_stop=visits, full_reference_visits=slots + residents * later +
            later + later * (later + 1) // 2,
            full_reference_count_kind='exact closed form for disjoint fixture; full walk NOT RUN'))
        print(a.namespace, 'P', later, 'F2 falsified at', visits, flush=True)
    receipt = dict(namespace=a.namespace, source_commit=F2,
        original_source_sha256=hashlib.sha256(original.encode()).hexdigest(),
        generated_source_sha256=sha(generated), binary_sha256=sha(binary),
        compile=compile_command, link=link_command, observations=rows)
    (a.output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
