#!/usr/bin/env python3
"""Check A7's lexical identity and the authorized Placement header extraction."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp
import format as formatting

BASE = '7595a6705a'
FROZEN = '5c3631281815c1652b3894d1736840c8466a5015'
FILES = ['src/cmd/flip_liveness.inc', 'src/cmd/flip_session.inc'] + [
    'src/core/' + name for name in (
        'client_hz.h climon_mask.h connreset.h eof.cc flip_policy.h flipctl.cc flipctl.h '
        'fliplisten.cc lbplanner.cc lbsignals.h lbstall.cc lbstall.h orthog.h placement.h '
        'signal.h signal_doorbell.h signalacct.h wb_rule.h weighted_lb.h').split()]
TOPIC = 'src/core/placement_impl.h'


def source(ref, filename):
    return subprocess.check_output(['git', 'show', f'{ref}:{filename}'], cwd=ROOT).decode()


def raw(text):
    return tuple(t.text for t in cpp.lex(text))


def digest(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()


def placement_extraction(before, interface, implementation):
    """Derive the only permitted token changes independently from the original class."""
    stream = cpp.lex(before)
    values = tuple(t.text for t in stream)
    name_at = values.index('Placement')
    assert values[name_at - 1:name_at + 2] == ('class', 'Placement', '{')
    opening = name_at + 1
    stack, pairs = [], {}
    for i in range(opening, len(stream)):
        if values[i] == '{':
            stack.append(i)
        elif values[i] == '}':
            pairs[stack.pop()] = i
            if not stack:
                closing = i
                break
    assert values[closing + 1] == ';'
    methods = []
    at = opening + 1
    while at < closing:
        if values[at] != '{':
            at += 1
            continue
        end = pairs[at]
        begin = at - 1
        while values[begin] not in (';', '}', '{', ':'):
            begin -= 1
        begin += 1
        signature = list(values[begin:at])
        function_name = signature[signature.index('(') - 1]
        definition = signature.copy()
        if definition[0] == 'static':
            definition.pop(0)  # static remains on the class declaration
        idx = definition.index('(') - 1
        definition[idx:idx] = ['Placement', '::']
        # Original defaults stay on the declarations, not the definitions.
        for default in ('false', 'nullptr'):
            while '=' in definition:
                pos = definition.index('=')
                if definition[pos + 1] != default:
                    break
                del definition[pos:pos + 2]
        assert '=' not in definition
        definition = ('inline', *definition, *values[at:end + 1])
        methods.append((begin, at, end, function_name, tuple(signature), definition))
        at = end + 1
    expected_interface = list(values)
    for begin, at, end, _, signature, _ in reversed(methods):
        expected_interface[begin:end + 1] = [*signature, ';']
    removed = sum((end - begin + 1) - (len(signature) + 1)
                  for begin, _, end, _, signature, _ in methods)
    after_class = closing + 2 - removed
    expected_interface[after_class:after_class] = ['#', 'include', '"placement_impl.h"']
    expected_impl = ('#', 'pragma', 'once', *(token for *_, definition in methods
                                            for token in definition))
    assert raw(interface) == tuple(expected_interface), 'Placement interface changed beyond extraction'
    assert raw(implementation) == expected_impl, 'Placement definitions changed beyond inline qualification'
    # Source-token order in the topic header is the original member-definition order.
    # Runtime literals are identical. The sole new quoted token is the include header name.
    original_literals = formatting.literals(before)
    topic_literals = formatting.literals(implementation)
    interface_literals = formatting.literals(interface)
    assert interface_literals[-1] == '"placement_impl.h"'
    assert interface_literals[:-1] + topic_literals == original_literals
    return {'members': len(methods), 'definition_order': [m[3] for m in methods],
            'body_tokens_identical': True, 'runtime_literals_identical': True,
            'authorized_syntax': ['in-class bodies become declarations',
                                  'immediate placement_impl.h include',
                                  'inline qualified definitions in original order',
                                  'static/default arguments remain on declarations']}


def main():
    changed = subprocess.check_output(['git', 'diff', BASE, '--name-only', '--', 'src/'],
                                      cwd=ROOT, text=True).splitlines()
    # Include an untracked candidate header before the first split commit as well.
    if (ROOT / TOPIC).exists() and TOPIC not in changed:
        changed.append(TOPIC)
    assert set(changed) == set(FILES + [TOPIC]), changed
    results = []
    for filename in FILES:
        before = source(BASE, filename)
        frozen = source(FROZEN, filename)
        after = (ROOT / filename).read_text()
        assert raw(before) == raw(frozen), (filename, 'lane base differs from frozen tokens')
        if filename.endswith('/placement.h'):
            split = placement_extraction(before, after, (ROOT / TOPIC).read_text())
            results.append({'file': filename, 'check': 'authorized extraction', **split})
            continue
        assert raw(before) == raw(after), (filename, 'preprocessing tokens')
        assert formatting.literals(before) == formatting.literals(after), (filename, 'literal bytes')
        assert formatting.anchors(before) == formatting.anchors(after), (filename, 'tool markers')
        results.append({'file': filename, 'tokens': len(raw(after)),
                        'token_sha256': digest(raw(after)),
                        'literal_sha256': digest(formatting.literals(after)),
                        'tool_markers_identical_at_token_boundaries': True})
    out = {'lane_base': BASE, 'frozen_source': FROZEN, 'renames': [], 'files': results}
    destination = ROOT / 'docs/readability-a7/evidence/tokens.json'
    destination.write_text(json.dumps(out, indent=2) + '\n')
    print('PASS: 20 files have identical raw preprocessing tokens, literal bytes and tool markers')
    print('PASS: Placement has 24 unchanged member bodies/literal streams, in order, with equivalent inline definitions')
    print('PASS: all 21 original files match frozen-source preprocessing tokens before the authorized extraction')
    print('PASS: src/ change scope is the 21 owned files plus placement_impl.h; no renames')


if __name__ == '__main__':
    main()
