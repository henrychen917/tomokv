#!/usr/bin/env python3
"""Policy-0/1 reply parity for the 22 standard writeback fixture shapes.

The live wire cannot force a particular Done prefix or staged-byte instant.
The same row also runs completion-unit trace cases for those exact states;
this battery checks boot identity and every reply on both real transports.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import _lib


STANDARD = [(1, 0, 0, 1, 0), (64, 1, 0, 0, 0), (64, 0, 512, 1, 0)]
STANDARD += [(n, done, 0, 1, 0) for n in (8, 16, 17, 32, 33, 64) for done in (0, 1, n)]
STANDARD += [(64, 1, 0, 1, 1)]
assert len(STANDARD) == len(set(STANDARD)) == 22


def check_replies(actual, expected, label):
    if actual != expected:
        raise AssertionError('writeback reply parity: ' + label)


def traces():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
    from lbstall_artifacts import Elf
    for suffix in ('', '-db0'):
        binary = Path(f'build/wb-rule{suffix}-completion-unit')
        for n, done, staged, _policy, scatter in STANDARD:
            for policy in (0, 1):
                for count in range(4):
                    case = f'trace-{n}-{done}-{staged}-{policy}-{scatter}-{count}'
                    result = subprocess.run([str(binary), case],
                                            text=True, capture_output=True, timeout=10)
                    if result.returncode or f'PASS wb-completion {case}' not in result.stdout:
                        raise AssertionError(f'exact writeback fixture {suffix}/{case}: {result.stdout}{result.stderr}')
        # Throwaway executable control: an always-defer wrapper must fail the
        # policy-zero assertion. Only a serverless unit is patched/executed.
        elf = Elf(binary)
        symbol = elf.functions()['wb_completion_defer']
        assert symbol['size'] >= 6
        section = elf.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3]
        broken = bytearray(elf.data)
        broken[offset:offset + 6] = b'\xb8\x01\x00\x00\x00\xc3'  # return true
        with tempfile.TemporaryDirectory(prefix='wb-policy-control-') as directory:
            mutant = Path(directory) / 'always-defer'
            mutant.write_bytes(broken)
            mutant.chmod(0o700)
            result = subprocess.run([str(mutant), 'trace-64-1-0-0-0-0'],
                                    text=True, capture_output=True, timeout=10)
            assert result.returncode == 1 and 'trace decision' in result.stderr, result
        print(f'PASS policy-zero always-defer control rejected ({suffix or "multi"}): trace decision')
    print('PASS 22 exact states x 2 policies x 4 counts x 2 namespaces (serverless)')


def live(host, port, policy):
    records = []
    with closing(_lib.Conn(host, port)) as admin:
        check_replies(admin.must('CONFIG', 'GET', 'wb-policy'),
                      [b'wb-policy', str(policy).encode()], 'boot CONFIG')
        check_replies(_lib.info(admin, 'WRITEBACK').get('wb_policy'), str(policy), 'INFO WRITEBACK')
        for index, (depth, prefix, staged, _original_policy, scatter) in enumerate(STANDARD):
            key = f'wb-policy:{index}:value'
            counter = f'wb-policy:{index}:counter'
            value = bytes(range(128))
            admin.must('SET', key, value)
            admin.must('SET', counter, '0')
            # A different owner is required for the scatter shape, rather than
            # merely spelling MGET twice on the same shard.
            other = key
            if scatter:
                owner = _lib.topology(admin).shard_owner
                sid = _lib.shard_of(admin, key)
                for candidate in range(4096):
                    other = f'wb-policy:scatter:{candidate}'
                    if owner[_lib.shard_of(admin, other)] != owner[sid]:
                        break
                else:
                    raise AssertionError('writeback scatter fixture never spanned owners')
                admin.must('SET', other, value)
            commands, expected = [], []
            for op in range(depth):
                if scatter and op == 0:
                    commands.append(_lib.encode('MGET', key, other))
                    expected.append([value, value])
                elif op % 3 == 0:
                    commands.append(_lib.encode('INCR', counter))
                    expected.append(op // 3 + 1 - int(bool(scatter)))
                elif op % 3 == 1:
                    commands.append(_lib.encode('SET', key, value))
                    expected.append(b'OK')
                else:
                    commands.append(_lib.encode('GET', key))
                    expected.append(value)
            with closing(_lib.Conn(host, port, timeout=10)) as conn:
                if staged:
                    # $504 CRLF + 504 payload bytes + CRLF = exactly 512 bytes.
                    conn.raw(_lib.encode('ECHO', b's' * 504))
                if prefix:
                    conn.raw(b''.join(commands[:prefix]))
                if prefix < depth:
                    conn.raw(b''.join(commands[prefix:]))
                if staged:
                    check_replies(conn.read(), b's' * 504, f'fixture {index} staged')
                replies = [conn.read() for _ in range(depth)]
                check_replies(replies, expected, f'fixture {index}')
                # Store the typed replies losslessly for the independent boot comparison.
                def encode(value):
                    if isinstance(value, bytes): return {'bytes': value.hex()}
                    if isinstance(value, list): return [encode(v) for v in value]
                    return value
                records.append(dict(fixture=list(STANDARD[index]), replies=encode(replies)))
    return records


def self_test():
    for mutated in ([b'OK', b'wrong'], [b'OK'], [b'value', b'OK']):
        try:
            check_replies(mutated, [b'OK', b'value'], 'throwaway wrong/missing/reordered reply')
        except AssertionError as error:
            assert 'writeback reply parity' in str(error)
        else:
            raise AssertionError('reply negative control passed')
    print('PASS writeback wrong/missing/reordered reply controls')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--traces', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int)
    parser.add_argument('--policy', type=int, choices=(0, 1))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.traces:
        traces()
    else:
        records = live(args.host, args.port, args.policy)
        if args.compare:
            check_replies(records, json.loads(args.compare.read_text()), '22 fixtures across boots')
        args.output.write_text(json.dumps(records, indent=2) + '\n')
        print(f'PASS policy {args.policy}: all 22 standard reply shapes')
