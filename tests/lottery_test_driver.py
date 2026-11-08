#!/usr/bin/env python3
"""Run an existing battery with observation-only markers; leave assertions intact."""
import hashlib
import ast
from python_anchors import statement, insert
import json
import os
from pathlib import Path
import sys
import time
import uuid

from _lib import Conn
from _gate_process import info


def main():
    path = Path(sys.argv[1]).resolve()
    sys.argv = [str(path), *sys.argv[2:]]
    if sys.argv[1:] == ['--list-generators']:
        exec(compile(path.read_text(), str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
        return
    port = int(os.environ['LOTTERY_PORT'])
    family = os.environ['LOTTERY_FAMILY']

    def observe(*command, parse=None):
        # One short-lived observer connection per call: the battery never runs
        # beside an extra idle client the gate does not have (maxclients,
        # CLIENT LIST and connection-count assertions stay exactly as gated).
        conn = Conn('127.0.0.1', port)
        try:
            return parse(conn) if parse else conn.must(*command)
        finally:
            conn.close()

    auto = os.environ.get('LOTTERY_AUTO_TRACE')
    metadata = None
    if auto:
        directory = Path(auto)
        directory.mkdir(parents=True, exist_ok=True)
        base = directory / uuid.uuid4().hex
        before = observe(parse=info)
        metadata = dict(pid=int(before['process_id']), trace=str(base.with_suffix('.trace')),
                        before=before, argv=sys.argv)
        observe('DEBUG', 'LOTTERY', 'ARM', os.environ['LOTTERY_MASK'], metadata['trace'])

    def mark(name):
        observe('DEBUG', 'LOTTERY', 'MARK', name)

    def config_sleep(seconds):
        time.sleep(seconds)
        # A single sample after the battery's existing propagation sleep, with
        # no poll/wait/retry. Failure to observe all owners is a missed attempt.
        if seconds >= .05:
            observe('DEBUG', 'LOTTERY', 'CONFIG')

    source = path.read_text()
    original_hash = hashlib.sha256(source.encode()).hexdigest()
    tree = ast.parse(source)
    changes = {}
    if family in ('blocking', 'servertail', 'slowlog'):
        modules = {alias.asname or 'time' for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for alias in node.names if alias.name == 'time'}
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'sleep'
                 and isinstance(node.func.value, ast.Name) and node.func.value.id in modules]
        if not calls:
            raise ValueError('missing propagation sleep anchor')
        for call in calls:
            call.func = ast.Name(id='lottery_config_sleep', ctx=ast.Load())
    if family == 'expwide':
        for name in ('fanout', 'exec', 'script', 'ordinary'):
            try:
                function = statement(source, tree, 'expiry-' + name)
                if not isinstance(function, ast.FunctionDef):
                    raise ValueError('expiry anchor must name a function')
                calls = [node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                         and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                         and node.value.func.id == function.name]
                if len(calls) != 1:
                    raise ValueError('expiry invocation is missing or ambiguous')
            except ValueError as error:
                raise ValueError('changed expiry section anchor: ' + name) from error
            changes[calls[0]] = (ast.parse(f'lottery_mark("expiry_section_{name}")').body, [])
    if path.name == 'differ.py':
        compare = statement(source, tree, 'tracking-compare')
        reset = statement(source, tree, 'tracking-reset')
        # Bind the comparison to the two collector results even when their local
        # identifiers change or the two assignments move onto separate lines.
        assigns = sorted([node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                          and compare.lineno <= node.lineno < reset.lineno],
                         key=lambda node: (node.lineno, node.col_offset))
        if len(assigns) != 2 or any(len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name)
                                   for node in assigns):
            raise ValueError('tracking collector anchor must contain two assignments')
        left, right = [node.targets[0].id for node in assigns]
        changes[compare] = (ast.parse('lottery_mark("tracking_compare_begin")').body, [])
        changes[reset] = ([], ast.parse(f'lottery_mark("tracking_compare_zero" if {left} == {right} == b"" else "tracking_compare_data")').body)
    tree = insert(tree, changes)
    print(f'LOTTERY battery sha256={original_hash} markers_only=1', flush=True)
    try:
        exec(compile(tree, str(path), 'exec'), dict(__name__='__main__', __file__=str(path),
             lottery_mark=mark, lottery_config_sleep=config_sleep))
    finally:
        if metadata is not None:
            metadata['after'] = observe(parse=info)
            metadata['stopped'] = observe('DEBUG', 'LOTTERY', 'STOP') == b'OK'
            base.with_suffix('.json').write_text(json.dumps(metadata, indent=2) + '\n')


if __name__ == '__main__':
    main()
