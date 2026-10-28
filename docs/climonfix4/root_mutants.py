#!/usr/bin/env python3
"""Root-isolated Tcl regressions, retaining all other final POST changes."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/climonfix4'
BUILD = ROOT / 'build/climonfix4/root-mutants'
POST = ROOT / 'build/climonfix4/tomokv-POST'
EXPECTED = 'ed7acc2bf7093e94a8e9afec7a899ae96b7e2c3274e836ea22c1061ae2f32f01'
CHANGES = {
    'PAUSE-MAY-REPLICATE': ('climon.cc',
        'return (op.spec->flags & CmdFlags::Write) || op.cmd_name().eq_icase("pfcount") ||\n        op.cmd_name().eq_icase("publish") || op.cmd_name().eq_icase("spublish");',
        'return (op.spec->flags & CmdFlags::Write) != 0; // planted: omit MAY_REPLICATE'),
    'PAUSE-SCRIPT-FLAGS': ('climon.cc',
        'return function_is_fcall(op) ? function_metadata_write(op) : script_metadata_write(op);',
        'return (op.spec->flags & CmdFlags::Write) != 0; // planted: ignore script flags'),
    'MONITOR-SCRIPT-CMDS': ('scripting.cc',
        'notify_monitor_script(*context->shard, *context->parent, nested,\n                                          context->monitor_multi_order);',
        '(void)context->monitor_multi_order; // planted: omit nested MONITOR delivery'),
    'RESET-CLEARS-LIBNAME': ('t_server.cc',
        '// Library identity describes the connection across RESET (Redis 7.4).',
        'meta->lib_name.clear(); meta->lib_ver.clear(); // planted: RESET loses library identity'),
    'RESET-MONITOR-ECHO': ('climon.cc',
        'const uint64_t excluded = op.cmd_name().eq_icase("reset") && op.argc() == 1 ? client->id() : 0;',
        'const uint64_t excluded = 0; // planted: echo RESET to its issuing monitor'),
    'CLIENT-LIST-CMD-NAME': ('t_server.cc',
        'meta->last_command = child ? child : command_metadata_for(*spec);',
        'meta->last_command = command_metadata_for(*spec); // planted: lose subcommand name'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def checked(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


def main():
    assert sha(POST) == EXPECTED
    assert not subprocess.check_output(['git', 'diff', 'c369ccc41', '--', 'src'], cwd=ROOT)
    subprocess.run(['make', '-q', 'all'], cwd=ROOT, check=True)
    recipe = subprocess.check_output(['make', '-n', '-W', 'build/src/main.o', 'all'], cwd=ROOT, text=True)
    link_template = shlex.split(next(s for s in recipe.splitlines()
                                    if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
    witnesses = json.loads((DOC / 'tcl-controls/witnesses.json').read_text())
    results_file = DOC / 'root-mutant-results.json'
    results = json.loads(results_file.read_text()) if results_file.exists() else []
    BUILD.mkdir(exist_ok=True)
    for root, (unit, before, after) in CHANGES.items():
        if any(r['root'] == root and r['post_sha256'] == EXPECTED for r in results):
            continue
        dest = BUILD / root
        dest.mkdir(exist_ok=True)
        source = dest / 'source'
        shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
        shutil.copytree(ROOT / 'third_party', source / 'third_party', dirs_exist_ok=True)
        path = source / 'src/cmd' / unit
        original = path.read_text()
        assert original.count(before) == 1, root
        path.write_text(original.replace(before, after))
        record = dict(root=root, post_sha256=EXPECTED, source_commit='c369ccc41',
                      source='src/cmd/' + unit, before=before, after=after,
                      source_before_sha256=hashlib.sha256(original.encode()).hexdigest(),
                      source_after_sha256=sha(path), compile=[])
        link = list(link_template)
        builds = []
        for namespace in ('normal', 'db0'):
            obj = dest / (namespace + '.o')
            command = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
                       '-DTOMO_JEMALLOC', '-I' + str(ROOT)]
            if namespace == 'db0':
                command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
            command += ['-c', str(path), '-o', str(obj)]
            record['compile'].append(command)
            builds.append((command, dest / (namespace + '.log')))
            old = 'build/' + ('db0/' if namespace == 'db0' else '') + 'src/cmd/' + unit.removesuffix('.cc') + '.o'
            assert old in link
            link[link.index(old)] = str(obj)
        # Only two translation units need rebuilding; use the lane's -j16 cap.
        makefile = dest / 'mutant.mk'
        makefile.write_text('.PHONY: normal db0\n' + ''.join(
            namespace + ':\n\t' + shlex.join(cmd) + ' >' + shlex.quote(str(log)) + ' 2>&1\n'
            for namespace, (cmd, log) in zip(('normal', 'db0'), builds)))
        record['build_command'] = ['make', '-j16', '-f', str(makefile), 'normal', 'db0']
        checked(record['build_command'], dest / 'make.log')
        binary = dest / 'tomokv'
        link[link.index('-o') + 1] = str(binary)
        checked(link, dest / 'link.log')
        record.update(binary=str(binary), binary_sha256=sha(binary), link=link,
                      object_sha256={p.name: sha(p) for p in dest.glob('*.o')})
        shutil.rmtree(source)
        print(root, 'built', record['binary_sha256'], flush=True)
        command = ['taskset', '-c', '16-31', 'bash', 'tests/gate.sh', 'quick',
                   '--server-cores', '16-23', '--load-cores', '24-31', '--server-smt', '',
                   '--load-smt', '', '--ports', '20220-20229', '--candidate-binary', str(binary)]
        env_delta = dict(REDIS74_ROOT='/home/user/Projects/redis', GATE_ONLY_JOBS='redis_tcl',
                         GATE_TCL_MANIFEST=str(DOC / 'tcl-controls' / (root + '.json')))
        logfile = dest / 'gate.log'
        with logfile.open('w') as log:
            rc = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **env_delta),
                                stdout=log, stderr=subprocess.STDOUT).returncode
        run = Path(re.search(r'artifacts: (\S+)', logfile.read_text())[1])
        test_unit, name = witnesses[root]
        record.update(command=command, env=env_delta, exit=rc, artifacts=str(run), modes={})
        for mode in ('1s', '2s'):
            path = run / 'jobs/redis_tcl' / ('redis-tcl-' + mode) / test_unit / 'result.json'
            result = json.loads(path.read_text())
            statuses = [e['status'] for e in result['events']
                        if e['test'] == name + ' in tests/' + test_unit + '.tcl']
            deadline = (not result['complete'] and result['exit_code'] != 0 and
                        statuses[-1:] == ['testing'] and
                        'TIMEOUT' in path.with_name('suite.log').read_text())
            # A missing or skipped witness is never a successful negative control.
            assert rc != 0 and 'testing' in statuses and 'ok' not in statuses
            assert 'err' in statuses or deadline, (root, mode, result)
            record['modes'][mode] = dict(result=str(path), statuses=statuses,
                                         timeout=deadline, error=result['error'])
        assert rc == 1
        receipt = dict(name='final14-mutant-' + root.lower(), exit=rc, artifacts=str(run),
                       replay_argv=command, env=env_delta, source_commit='c369ccc41 + isolated mutation',
                       binary_sha256=record['binary_sha256'], post_sha256=EXPECTED,
                       gate_sha256=sha(ROOT / 'tests/gate.sh'),
                       manifest_sha256=sha(env_delta['GATE_TCL_MANIFEST']),
                       log=str(logfile), log_sha256=sha(logfile), expected='Named witness fails in both modes',
                       jobs=['release', 'redis_tcl'])
        save(DOC / 'jobs' / (receipt['name'] + '.json'), receipt)
        results.append(record)
        save(results_file, results)
        subprocess.run(['python3', str(DOC / 'archive_jobs.py')], cwd=ROOT, check=True)
        binary.unlink()
        for obj in dest.glob('*.o'):
            obj.unlink()
        record['binary_and_objects_pruned'] = True
        save(results_file, results)
        print(root, 'named failure verified in both modes; arm pruned', flush=True)
    assert len(results) == len(CHANGES)


if __name__ == '__main__':
    main()
