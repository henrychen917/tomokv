#!/usr/bin/env python3
"""Generate COMMAND DOCS wire data from the pinned command metadata, offline.

Only registered TomoKV commands and their metadata children are advertised.
Normal builds consume the checked-in result; no Redis implementation is linked.
"""
import argparse
import json
from pathlib import Path
from gen_cmdmeta import REDIS_VERSION, REDIS_REVISION, tomo_commands


class Flags(list):
    pass


def argument(arg):
    out = {'name': arg['name'].lower(), 'type': arg['type']}
    if arg['type'] not in ('oneof', 'block'):
        out['display_text'] = arg.get('display', arg['name']).lower()
    for key in ('key_spec_index', 'token', 'summary', 'since', 'deprecated_since'):
        if key in arg:
            out[key] = arg[key].upper() if key == 'token' else arg[key]
    flags = Flags(key for key in ('optional', 'multiple', 'multiple_token') if arg.get(key))
    if flags:
        out['flags'] = flags
    if arg['type'] in ('oneof', 'block'):
        out['arguments'] = [argument(child) for child in arg['arguments']]
    return out


def docs(row):
    out = {key: row[key] for key in ('summary', 'since', 'group', 'complexity') if key in row}
    out['group'] = out['group'].replace('_', '-')
    if row.get('doc_flags'):
        out['doc_flags'] = Flags(flag.lower() for flag in ('DEPRECATED', 'SYSCMD')
                                 if flag in row['doc_flags'])
    for key in ('deprecated_since', 'replaced_by', 'history'):
        if row.get(key):
            out[key] = row[key]
    if row.get('arguments'):
        out['arguments'] = [argument(arg) for arg in row['arguments']]
    return out


def wire(value, resp3):
    if isinstance(value, dict):
        return (('%' if resp3 else '*') + str(len(value) * (1 if resp3 else 2)) + '\r\n' +
                ''.join(wire(k, resp3) + wire(v, resp3) for k, v in value.items()))
    if isinstance(value, Flags):
        return ('~' if resp3 else '*') + str(len(value)) + '\r\n' + ''.join('+' + x + '\r\n' for x in value)
    if isinstance(value, list):
        return '*' + str(len(value)) + '\r\n' + ''.join(wire(x, resp3) for x in value)
    if isinstance(value, int):
        return ':' + str(value) + '\r\n'
    return '$' + str(len(value.encode())) + '\r\n' + value + '\r\n'


def generate(root, redis):
    assert f'"{REDIS_VERSION}"' in (redis / 'src/version.h').read_text()
    names = tomo_commands(root)
    rows = {}
    for path in sorted((redis / 'src/commands').glob('*.json')):
        for name, row in json.loads(path.read_text()).items():
            parent = row.get('container', '').lower()
            name = name.lower()
            if (parent or name) in names:
                rows[(parent + '|' if parent else '') + name] = docs(row)
    rows['flip'] = dict(summary='Changes the TomoKV thread roles.', since='1.0', group='server')
    for name, row in list(rows.items()):
        if '|' in name:
            rows[name.split('|')[0]].setdefault('subcommands', {})[name] = row
    lines = [f'// Generated from Redis {REDIS_VERSION} command JSON ({REDIS_REVISION}).',
             '// Regenerate with tools/gen_cmddocs.py; metadata only, no Redis implementation.',
             'static constexpr CommandDocs kCommandDocs[] = {']
    for name, row in sorted(rows.items()):
        lines.append('    {' + ', '.join(json.dumps(x, ensure_ascii=False)
                                        for x in (name, wire(row, False), wire(row, True))) + '},')
    return '\n'.join(lines + ['};', ''])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--redis-root', required=True, type=Path)
    p.add_argument('--output', type=Path, default=Path('src/cmd/cmddocs_generated.inc'))
    p.add_argument('--check', action='store_true')
    a = p.parse_args()
    result = generate(Path(__file__).resolve().parents[1], a.redis_root)
    if a.check:
        assert a.output.read_text() == result, 'COMMAND DOCS metadata drift'
    else:
        a.output.write_text(result)
