#!/usr/bin/env python3
"""Read-only A3 token/literal/marker and file-ownership proof against both baselines."""
from bisect import bisect_left
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import source_tokens as cpp

BASE = '9a09e5919092cc5e33aaf1e49e55994bdf8439b5'
FROZEN = '5c3631281815c1652b3894d1736840c8466a5015'
OWNED = ('src/cmd/climon.inc', 'src/core/io_loop.h', 'src/core/pubsub.inc',
         'src/core/pubsub_event.h', 'src/core/read_local.h', 'src/core/read_local_parse.inc')
BEGIN = '// BEGIN R7 GENERATED ENVELOPES'
END = '// END R7 GENERATED ENVELOPES'


def source(rev, name):
    return subprocess.check_output(['git', 'show', f'{rev}:{name}'], cwd=ROOT).decode()


def literal_tokens(text):
    return tuple(m[0] for m in cpp.LEXER.finditer(text) if m.lastgroup in ('raw', 'string'))


def markers(text):
    ends = [token.end for token in cpp.lex(text)]
    return tuple((m[0], bisect_left(ends, m.start())) for m in cpp.LEXER.finditer(text)
                 if m.lastgroup == 'comment' and 'TOMO_TOOL_' in m[0])


def outside_envelope(text):
    prefix, rest = text.split(BEGIN, 1)
    _, suffix = rest.split(END, 1)
    return prefix, suffix


def comment_groups(text):
    ends = [token.end for token in cpp.lex(text)]
    groups = {}
    for m in cpp.LEXER.finditer(text):
        if m.lastgroup != 'comment' or 'TOMO_TOOL_' in m[0]:
            continue
        body = re.sub(r'^// ?', '', m[0]) if m[0].startswith('//') else m[0][2:-2]
        groups.setdefault(bisect_left(ends, m.start()), []).append(body)
    return {offset: ' '.join(' '.join(parts).split()) for offset, parts in groups.items()}


def main():
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', BASE, '--', 'src'], cwd=ROOT, text=True).splitlines()
    assert set(changed) == set(OWNED) | {'src/core/reorder.cc'}, changed
    rows = []
    rewrites = Counter()
    landmarks = Counter()
    for name in changed:
        after = (ROOT / name).read_bytes().decode()
        before = source(BASE, name)
        code = tuple(token.text for token in cpp.lex(after))
        for rev in (BASE, FROZEN):
            original = source(rev, name)
            assert code == tuple(token.text for token in cpp.lex(original)), (name, rev, 'tokens')
            assert literal_tokens(after) == literal_tokens(original), (name, rev, 'literals')
        assert markers(before) == markers(after), (name, 'tool marker text/boundary')
        if name not in OWNED:
            assert outside_envelope(before) == outside_envelope(after), name
        else:
            old_groups, new_groups = comment_groups(before), comment_groups(after)
            rewrites[name] = sum(body not in new_groups.get(offset, '')
                                 for offset, body in old_groups.items())
            landmarks[name] = len(re.findall(r'// Phase [0-9]+:', after))
        rows.append(dict(file=name, preprocessing_tokens=len(code),
                         tokens_vs_base='IDENTICAL', tokens_vs_frozen='IDENTICAL',
                         literal_stream='BYTE_IDENTICAL', tool_markers='EXACT'))
    result = dict(base=BASE, frozen=FROZEN, renames=[], files=rows,
                  rewritten_comment_groups=dict(rewrites), rewritten_total=sum(rewrites.values()),
                  phase_landmarks=dict(landmarks), landmarks_total=sum(landmarks.values()))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
