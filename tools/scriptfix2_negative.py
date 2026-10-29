#!/usr/bin/env python3
"""Independently select each planted regression and require its named Tcl witness.

The complete positive/combined-negative jobs remain gate.sh jobs. This supplements
them with per-root isolation using unchanged upstream files and assertion manifests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WITNESSES = {
    'EVAL-SHEBANG': 'Shebang support for lua engine',
    'EVALSHA-SHA-CASE': 'EVALSHA - Can we call a SHA1 in uppercase?',
    'FCALL-NAME-CASE': 'FUNCTION - test function case insensitive',
    'FUNCTION-LOAD-ENV': 'FUNCTION - test getmetatable on script load',
    'FUNCTION-REGISTER-ARGS': 'LIBRARIES - test registration with empty name',
    'FUNCTION-SHEBANG-META': 'FUNCTION - function test name with quotes',
    'FUNCTION-SUBCMD-ARGS': 'FUNCTION - test function restore with wrong number of arguments',
    'LUA-REDIS-API': 'LUA redis.error_reply API with CRLF injection attempt',
    'LUA-SANDBOX-GLOBALS': 'Binary code loading failed',
    'SCRIPT-ERROR-WORDING': 'EVAL - No arguments to redis.call/pcall is considered an error',
    'SCRIPT-NUMBER-ARG': 'Number conversion precision test (issue #1118)',
    'SCRIPT-REPLY-DEPTH': 'Script return recursive object',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--root', choices=WITNESSES)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = json.loads((ROOT / 'tests/redis_tcl_passing.json').read_text())
    results = dict(binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(), rows=[])
    selected = [args.root] if args.root else WITNESSES
    for root in selected:
        unit = 'unit/functions' if root.startswith(('FUNCTION-', 'FCALL-')) else 'unit/scripting'
        required = {WITNESSES[root]}
        if root == 'EVALSHA-SHA-CASE':
            required.add('EVAL - is Lua able to call Redis API?')
        if root == 'FCALL-NAME-CASE':
            required.add('FUNCTION - test replace argument')
        manifest = json.loads(json.dumps(original))
        spec = manifest['files'][unit]
        all_names = {name.split(' in tests/')[0] for name in spec['passed_tests']}
        assert required <= all_names
        spec['passed_tests'] = [name for name in spec['passed_tests']
                                if name.split(' in tests/')[0] in required]
        spec['skip_tests'] = sorted(set(spec['skip_tests']) | (all_names - required))
        manifest['files'] = {unit: spec}
        scoped = args.output / f'{root}-manifest.json'
        scoped.write_text(json.dumps(manifest, indent=2) + '\n')
        for mode in ('1s', '2s'):
            output = args.output / f'{root}-{mode}'
            command = [sys.executable, 'tests/redis_tcl.py', '--redis-root', '/home/user/Projects/redis',
                       '--binary', str(args.binary.resolve()), '--mode', mode, '--cores', args.cores,
                       '--ratio', '6:2', '--port', str(args.port),
                       '--controller-port', str(args.port + 1), '--baseport', str(args.port + 2),
                       '--manifest', str(scoped.resolve()), '--output', str(output.resolve())]
            positive = command.copy()
            positive[-1] = str(output.resolve()) + '-unarmed'
            with (args.output / f'{root}-{mode}-unarmed.log').open('w') as log:
                unarmed = subprocess.run(positive, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, TOMO_SCRIPTFIX2_BREAK=''))
            with (args.output / f'{root}-{mode}.log').open('w') as log:
                run = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     env=dict(os.environ, TOMO_SCRIPTFIX2_BREAK=root))
            report = json.loads((output / 'summary.json').read_text())
            errors = [event['test'].split(' in tests/')[0] for row in report['rows']
                      for event in row['events'] if event['status'] == 'err']
            caught = unarmed.returncode == 0 and run.returncode == 1 and WITNESSES[root] in errors
            results['rows'].append(dict(root=root, mode=mode, exit_code=run.returncode,
                                        unarmed_exit_code=unarmed.returncode,
                                        witness=WITNESSES[root], detected=caught,
                                        failed_named_tests=sorted(set(errors) - {''})))
            (args.output / 'isolation.json').write_text(json.dumps(results, indent=2) + '\n')
            print(root, mode, 'DETECTED' if caught else 'MISSED', flush=True)
            for checkout in (output / 'checkout', Path(str(output) + '-unarmed') / 'checkout'):
                shutil.rmtree(checkout)
    return int(not all(row['detected'] for row in results['rows']))


if __name__ == '__main__':
    sys.exit(main())
