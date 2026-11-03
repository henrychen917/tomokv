#!/usr/bin/env python3
"""PRE/POST controls for existing optional EOF and INFO diagnostic gate jobs."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import wave11_counts as native
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/netfix2/eof-native'
DOC = ROOT / 'docs/netfix2/regressions/optional-diagnostics'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    assert os.sched_getaffinity(0) <= set(range(8, 16))
    os.environ['LC_ALL'] = 'C'
    BUILD.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    original = (ROOT / 'tests/wave14_epoll_eof.cc').read_text()
    # Keep each original assertion, but isolate the four cases so one failed
    # EOF case cannot prevent the other mode or its open-peer control from firing.
    fixture = BUILD / 'all_modes.cc'
    fixture.write_text('#include <sys/wait.h>\n' + original.split('int main() {')[0] + r'''
int main() {
    void (*cases[])() = {
        [] { tomo::NetcmdRegression::edge<false>(false); },
        [] { tomo::NetcmdRegression::edge<true>(false); },
        [] { tomo::NetcmdRegression::edge<false>(true); },
        [] { tomo::NetcmdRegression::edge<true>(true); }
    };
    bool failed = false;
    for (auto test : cases) {
        const pid_t child = ::fork();
        if (child < 0) return 2;
        if (!child) { test(); std::exit(0); }
        int status = 0;
        if (::waitpid(child, &status, 0) != child) return 2;
        failed |= !WIFEXITED(status) || WEXITSTATUS(status) != 0;
    }
    return failed ? 1 : 0;
}
''')
    shutil.copy2(fixture, DOC / fixture.name)
    native.BUILD = BUILD
    native.DOC = DOC / 'builds'
    rows = []
    for arm in ('PRE', 'POST'):
        source, objects = ((ROOT / 'build/netfix2/pre-source', ROOT / 'build/netfix2')
                           if arm == 'PRE' else (ROOT, ROOT / 'build'))
        arms = BUILD / arm
        arms.mkdir(exist_ok=True)
        for namespace in ('normal', 'db0'):
            binary = native.build(arm, source, objects, namespace, str(fixture))
            elf = Elf(binary)
            text_before = elf.section_data(elf.names.index('.text'))
            subprocess.run(['strip', '-p', '--strip-debug', str(binary)], check=True)
            elf = Elf(binary)
            assert elf.section_data(elf.names.index('.text')) == text_before
            receipt = native.DOC / arm / (namespace + '-build.json')
            record = json.loads(receipt.read_text())
            record['unstripped_probe_sha256'] = record['probe_sha256']
            record['probe_sha256'] = sha(binary)
            record['debug_stripped_text_unchanged'] = True
            receipt.write_text(json.dumps(record, indent=2) + '\n')
            link = arms / namespace
            if link.is_symlink(): link.unlink()
            link.symlink_to(binary)
            # Frozen production objects and the compile/link receipts suffice
            # to regenerate these temporary fixture/linker copies.
            for name in ('probe.o', 'original-main.o'):
                (binary.parent / name).unlink()
        dest = DOC / arm
        dest.mkdir(exist_ok=True)
        candidate = ROOT / 'build/netfix2' / arm
        env = dict(os.environ, GATE_CORRECTNESS_SHARED_CPUS='1', GATE_PROOF_NO_RATES='1',
                   GATE_ONLY_JOBS='wave14_epoll_eof wave14_eof_data rootcompat-errorstats',
                   GATE_LOAD_CORES='8-15', GATE_DIFFER_ORACLE_CORES='8-15',
                   REDIS74_ROOT='/home/user/Projects/redis', WAVE14_EOF_DIRECTORY=str(arms))
        command = ['taskset', '-c', '8-15', 'tests/gate.sh', 'quick', '--server-cores', '8-15',
                   '--load-cores', '8-15', '--load-smt', '', '--ports', '21100-21199',
                   '--candidate-binary', str(candidate)]
        with (dest / 'gate.log').open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        run = Path(re.search(r'artifacts: (.+)', (dest / 'gate.log').read_text())[1])
        for name in ('ledger.partial', 'plan.sh'):
            shutil.copy2(run / name, dest / name)
        for job in (run / 'jobs').iterdir():
            target = dest / job.name
            target.mkdir(exist_ok=True)
            for path in job.iterdir():
                if path.is_file() and (path.suffix in ('.log', '.txt') or path.name in ('ledger', 'done')):
                    shutil.copy2(path, target / path.name)
            path = job / 'half-close/results.json'
            if path.exists(): shutil.copy2(path, target / 'results.json')
        row = dict(arm=arm, sha256=sha(candidate), exit=result.returncode, run=str(run),
                   command=command, native_directory=str(arms))
        rows.append(row)
        print(json.dumps(row), flush=True)
    (DOC / 'runs.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
