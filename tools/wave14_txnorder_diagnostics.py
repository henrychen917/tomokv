#!/usr/bin/env python3
"""Run the unchanged transaction-order gate job with failure-only stack capture."""
import argparse
import json
import os
import subprocess
import time

from wave14 import ROOT, DOC, BUILD, save, sha


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--binary', default=str(BUILD / 'post-r7/tomokv'))
    args = parser.parse_args()
    deadline = time.monotonic() + 12 * 3600
    results = DOC / 'final-epoll-results.json'
    while not results.exists() or len(json.loads(results.read_text())) != 4:
        assert time.monotonic() < deadline, 'epoll sweep did not release CPUs16-31'
        time.sleep(1)
    directory = BUILD / 'txnorder-capture'
    directory.mkdir(exist_ok=True)
    source = directory / 'launch.c'
    source.write_text('''#include <sys/prctl.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv) {
    (void)argc;
    const char *native = getenv("WAVE14_TXNORDER_NATIVE");
    if (!native || native[0] != '/' || prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0)) return 125;
    argv[0] = (char *)native;
    execv(native, argv);
    return 126;
}
''')
    launcher = directory / 'launch'
    subprocess.run(['cc', '-O2', str(source), '-o', str(launcher)], check=True)
    env = dict(os.environ, LC_ALL='C', WAVE14_TXNORDER_CAPTURE='1',
               WAVE14_TXNORDER_NATIVE=str(args.binary))
    save(DOC / (args.tag + '-native.json'), dict(native=args.binary,
        native_sha256=sha(args.binary), launcher_sha256=sha(launcher), source_sha256=sha(source),
        purpose='Exec the exact native arm with same-user ptrace allowed; attach only after an assertion fails. '
                'No production source, binary bytes, bounds or success criteria change.'))
    command = ['python3', 'tools/wave14.py', 'jobs', '--tag', args.tag, '--engine', 'epoll',
        '--jobs', 'txnorder-fused-0', '--binary', str(launcher), '--server-cores', '16-23',
        '--load-cores', '24-31', '--ports', '20096-20098']
    raise SystemExit(subprocess.run(command, cwd=ROOT, env=env).returncode)


if __name__ == '__main__':
    main()
