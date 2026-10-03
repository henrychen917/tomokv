#!/usr/bin/env python3
"""Build-only DEBUG counter overlays, or probe an externally started proof arm.

No production counter, configuration knob, listener, or load generator is added.
The probe is a bounded correctness check; mainline owns every live invocation.
"""
import argparse
import json
from pathlib import Path
import re
import time

import _lib

ROOT = Path(__file__).resolve().parents[1]


def instrument(pre, post, output):
    rules = ['include Makefile\n']
    for arm, objects in [('PRE', pre), ('POST', post)]:
        dest = output / ('LIVE-' + arm)
        dest.mkdir(parents=True, exist_ok=True)
        replacements = {}
        for name in ('l4prebuild', 't_server'):
            relative = Path('src/cmd') / (name + '.cc')
            # These two production files are unchanged by this lane. Read PRE too
            # so later source drift cannot quietly alter the reference overlay.
            before = pre / 'source' / relative
            original = (ROOT / relative).read_text()
            assert before.read_text() == original, ('counter overlay source drift', relative)
            if name == 'l4prebuild':
                original = '#include <atomic>\n#include <cstdint>\nnamespace tomo {\n' \
                    'static std::atomic<uint64_t> splitlocal_prebuilt{0};\n' \
                    'uint64_t splitlocal_prebuild_count() { return splitlocal_prebuilt.load(std::memory_order_relaxed); }\n' \
                    '}\n' + original
                needle = '    op.zc_shard = kPrebuiltSetMarker;'
                assert original.count(needle) == 1
                original = original.replace(needle, needle + '\n    splitlocal_prebuilt.fetch_add(1, std::memory_order_relaxed);')
            else:
                original = '#include <cstdint>\nnamespace tomo { uint64_t splitlocal_prebuild_count(); }\n' + original
                needle = '    const Slice subcommand = op.arg(1);'
                assert original.count(needle) == 1
                original = original.replace(needle, needle + '\n'
                    '    if (eq_icase(subcommand, "splitlocal-prebuilds") && op.argc() == 2) {\n'
                    '        reply_int(op.sink(), splitlocal_prebuild_count());\n'
                    '        return;\n    }')
            source = dest / (name + '.cc')
            source.write_text(original)
            for ns, flags in [('', ''), ('db0/', '-DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0')]:
                target = dest / ns / (name + '.o')
                target.parent.mkdir(parents=True, exist_ok=True)
                replacements[objects / ns / relative.with_suffix('.o')] = target
                rules.append(f'{target}: {source}\n\t$(CXX) $(CXXFLAGS) $(JEFLAGS) {flags} '
                             f'-I. -Isrc/cmd -c $< -o $@\n')
        # Preserve the real production link order, including the isolated R7 tail.
        production_src = (ROOT / 'Makefile').read_text().split('LDLIBS   += -lssl')[0]
        files = re.findall(r'\bsrc/[\w/]+\.cc\b', production_src)
        assert len(files) == len(set(files)) == 42, 'production object inventory'
        linked = [replacements.get(objects / ns / Path(file).with_suffix('.o'),
                                   objects / ns / Path(file).with_suffix('.o'))
                  for ns in ('db0/', '') for file in files]
        target = dest / 'tomokv'
        # Existing production objects are inputs, never rebuilt via this overlay.
        rules.append(f'{target}: ' + ' '.join(map(str, replacements.values())) + '\n'
                     '\t$(CXX) $(CXXFLAGS) ' + ' '.join(map(str, linked)) +
                     ' -o $@ $(JELIBS) $(LDLIBS) -lm\n')
    makefile = output / 'live.mk'
    makefile.write_text('\n'.join(rules))
    print('Counter overlays emitted:', makefile)


def probe(host, port, mode, overlap, database, output):
    conn = _lib.Conn(host, port, timeout=15)
    keys = []
    try:
        config = conn.must('CONFIG', 'GET', '*')
        config = dict(zip(config[::2], config[1::2]))
        for name, wanted in [('thread-mode', mode), ('read-local', '1'),
                             ('overlap', str(overlap)),
                             ('key-lb', '0'), ('client-lb', '0'), ('flip-auto', '0')]:
            assert config.get(name.encode()) == wanted.encode(), ('configuration', name, config.get(name.encode()))
        assert conn.must('SELECT', database) == b'OK'
        tid = conn.must('DEBUG', 'IO-THREAD')
        topo = _lib.topology(conn)
        assert len(topo.shard_owner) == 16
        prefix = 'splitlocal:%d' % time.time_ns()
        for key, _, owner in _lib.probe_keys(conn, prefix, topo):
            if owner != tid: keys.append(key)
            if len(keys) == 32: break
        assert len(keys) == 32, 'fresh foreign-owner keys armed'
        before = conn.must('DEBUG', 'SPLITLOCAL-PREBUILDS')
        assert isinstance(before, int), 'instrumented counter available'
        value = b'x' * 1024
        operations = 256
        # Eight rounds, one command at a time: no inbox backpressure can
        # inflate the successful-candidate count through refused-post retries.
        for i in range(operations):
            key = keys[i % len(keys)]
            assert conn.must('SET', key, value) == b'OK', 'SET reply'
            assert conn.must('GET', key) == value, '1 KiB SET read-your-own-write'
        after = conn.must('DEBUG', 'SPLITLOCAL-PREBUILDS')
        expected = operations if mode == '1s' else 0
        assert after - before == expected, ('prebuild count', after - before, expected)
        assert conn.must('DEBUG', 'IO-THREAD') == tid, 'connection owner stable'
        assert _lib.topology(conn).shard_owner == topo.shard_owner, 'shard owners stable'
        receipt = dict(mode=mode, overlap=overlap, database=database, sets=operations,
                       value_bytes=len(value), prebuilds=after-before, expected=expected,
                       foreign_keys=len(keys), ryow=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + '\n')
        print('PASS splitlocal prebuild counter:', json.dumps(receipt))
    finally:
        try:
            if keys: conn.must('DEL', *keys)
        finally: conn.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    i = sub.add_parser('instrument')
    i.add_argument('--pre', type=Path, default=Path('build/splitlocal/PRE'))
    i.add_argument('--post', type=Path, default=Path('build'))
    i.add_argument('--output', type=Path, default=Path('build/splitlocal'))
    c = sub.add_parser('probe')
    c.add_argument('host'); c.add_argument('port', type=int); c.add_argument('mode', choices=['1s','2s'])
    c.add_argument('overlap', type=int, choices=[0,1]); c.add_argument('database', type=int)
    c.add_argument('output', type=Path)
    args = p.parse_args()
    if args.action == 'instrument': instrument(args.pre, args.post, args.output)
    else: probe(args.host, args.port, args.mode, args.overlap, args.database, args.output)
