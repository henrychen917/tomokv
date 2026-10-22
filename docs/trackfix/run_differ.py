"""Unmodified standard differential, both engines and both geometries."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from run_proof import ROOT, BASE, DOC, environment, engine_binary


def run(spec):
    index, arm, engine, geometry = spec
    label = f'{arm}-{engine}-{geometry}'
    dest = DOC / 'differ' / label
    dest.mkdir(parents=True, exist_ok=False)
    binary = ROOT / ('build/tomokv-PRE' if arm == 'PRE' else 'build/tomokv')
    wrapper = engine_binary(binary, engine, label)
    env = environment()
    env.update(GATE_DIFFER_OUT=str(BASE / 'differ' / label),
               GATE_DIFFER_GEOMETRY=geometry, GATE_RUN_ID='trackfix-standard')
    argv = ['taskset', '-c', '105-111', 'bash', 'tests/differ_gate.sh', str(wrapper),
            str(22850 + index * 2), str(22851 + index * 2), '96-103', '6:2']
    (dest / 'command.json').write_text(json.dumps(dict(argv=argv, engine=engine,
        geometry=geometry, arm=arm), indent=2) + '\n')
    with (dest / 'output.log').open('w') as log:
        rc = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    result = dict(arm=arm, engine=engine, geometry=geometry, returncode=rc)
    (dest / 'result.json').write_text(json.dumps(result) + '\n')
    print(result, flush=True)
    return result


if __name__ == '__main__':
    arm = sys.argv[1]
    # These are protocol correctness comparisons, with no rate or merit claim.
    cases = [(i, arm, engine, geometry) for i, (engine, geometry) in enumerate(
        [('epoll', 'split'), ('uring', 'split'), ('epoll', 'armed-fused'), ('uring', 'armed-fused')])]
    environment()  # create wrappers/symlinks before starting independent jobs
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, cases))
    (DOC / 'differ' / f'{arm}-results.json').write_text(json.dumps(results, indent=2) + '\n')
