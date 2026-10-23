"""Shared lifecycle and receipt support for the serverfix directed batteries."""
import argparse
import traceback
from pathlib import Path

from authfix import Run, Server, Resp, clean, is_error


def main(probe):
    parser = argparse.ArgumentParser(description=probe.__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--oracle', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--cores', required=True)
    parser.add_argument('--ratio', default='6:2')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    failures = 0
    for binary, oracle in [(args.oracle, True), (args.binary, False)]:
        run = Run(args, binary, oracle)
        for mode in run.modes():
            for engine in (['redis'] if oracle else ['uring', 'epoll']):
                label = mode + '-' + engine
                extra = [] if oracle else ['--net-io', engine]
                try:
                    probe(run, mode, label, extra)
                except Exception:
                    traceback.print_exc()
                    run.check(label + ' completed every assertion', False, True)
        failures += run.finish()
    print(f'{probe.__module__}: {failures} failed checks; evidence {args.output}', flush=True)
    return bool(failures)
