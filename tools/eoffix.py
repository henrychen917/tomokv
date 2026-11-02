#!/usr/bin/env python3
"""Selected correctness jobs on the eoffix allocation; never measure rates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/eoffix'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', required=True)
    p.add_argument('--jobs', required=True)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--engine', choices=['uring', 'epoll'], default='epoll')
    p.add_argument('--port', type=int, default=21900)
    p.add_argument('--repeat', type=int, default=1)
    p.add_argument('--capture', action='store_true')
    p.add_argument('--keep-going', action='store_true')
    p.add_argument('--archive-data', action='store_true',
                   help='Archive completed large AOF data between repeated correctness jobs')
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(8))
    assert 21900 <= a.port <= 21997 and a.repeat >= 1
    assert not {'flip_saturated', 'efficiency', 'abba', 'nic'} & set(a.jobs.split())
    native = a.binary.resolve(); binary = native
    env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
        GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
        GATE_CORRECTNESS_SHARED_CPUS='1', GATE_PROOF_NO_RATES='1',
        GATE_ONLY_JOBS=a.jobs, GATE_NET_IO=a.engine, GATE_PROOF_NET_IO=a.engine,
        GATE_DIFFER_NET_IO=a.engine, CXX='g++ -gz=zlib', CC='cc -gz=zlib')
    if a.capture:
        directory = ROOT/'build/eoffix/capture'; directory.mkdir(parents=True, exist_ok=True)
        source = directory/'launch.c'
        source.write_text('''#include <sys/prctl.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv) {
    (void)argc;
    char *native = getenv("WAVE14_TXNORDER_NATIVE");
    if (!native || native[0] != '/' || prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0)) return 125;
    argv[0] = native;
    execv(native, argv);
    return 126;
}
''')
        binary = directory/'launch'
        subprocess.run(['cc', '-O2', str(source), '-o', str(binary)], check=True)
        env.update(WAVE14_TXNORDER_CAPTURE='1', WAVE14_TXNORDER_NATIVE=str(native))
    DOC.mkdir(parents=True, exist_ok=True)
    failed = False
    for index in range(1, a.repeat + 1):
        tag = a.tag + (f'-{index:02d}' if a.repeat > 1 else '')
        receipt = DOC/(tag+'.json')
        assert not receipt.exists(), 'never overwrite an attempt'
        env['GATE_LEDGER'] = str(DOC/tag)
        command = ['tests/gate.sh', 'full', '--server-cores', '0-7', '--load-cores', '0-7',
            '--server-smt', '', '--load-smt', '', '--ports', f'{a.port}-{a.port+2}',
            '--candidate-binary', str(binary)]
        record = dict(command=command, native=str(native), native_sha256=sha(native),
            launcher_sha256=sha(binary), engine=a.engine, jobs=a.jobs,
            env={k: v for k, v in env.items() if k.startswith(('GATE_', 'WAVE14_')) or k == 'LC_ALL'})
        (DOC/(tag+'-started.json')).write_text(json.dumps(record, indent=2)+'\n')
        logfile = DOC/(tag+'.log')
        with logfile.open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        record['exit_code'] = result.returncode
        runs = re.findall(r'^  artifacts: (.+)$', logfile.read_text(), re.M)
        if runs:
            run = Path(runs[0]); record['directory'] = str(run)
            record['ledgers'] = {str(x.relative_to(run)): x.read_text() for x in run.glob('jobs/*/ledger')}
            record['captures'] = [str(x.relative_to(run)) for x in run.glob('jobs/**/capture.json')]
            archive = DOC/(tag+'.tar.gz')
            with tarfile.open(archive, 'w:gz') as tar:
                for path in sorted(run.rglob('*')):
                    # Preserve textual diagnostics, AOF manifests and failure stacks. Large
                    # data generations stay in the run directory until explicitly archived.
                    if path.is_file() and path.stat().st_size < 16*1024*1024:
                        tar.add(path, arcname=str(path.relative_to(run)), recursive=False)
            record['archive_sha256'] = sha(archive)
        assert sha(native) == record['native_sha256'], 'native arm changed during proof'
        receipt.write_text(json.dumps(record, indent=2)+'\n')
        print(tag, 'exit', result.returncode, 'captures', record.get('captures', []), flush=True)
        if a.archive_data:
            subprocess.run(['python3', 'tools/eoffix_archive_data.py'], cwd=ROOT, check=True)
        if result.returncode:
            failed = True
            if not a.keep_going:
                raise SystemExit(result.returncode)
    raise SystemExit(int(failed))


if __name__ == '__main__':
    main()
