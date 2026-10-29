#!/usr/bin/env python3
"""Supplement the frozen matrix with equivalent no-writes FCALL functions."""
import concurrent.futures
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/climonfix5'
BUILD = ROOT / 'build/climonfix5'
spec = importlib.util.spec_from_file_location('climonfix5_scopes', DOC / 'scopes.py')
scopes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scopes)
COMMITS = {'pre': '393d6ceb1', 'c4': 'c369ccc41'}


def main():
    os.sched_setaffinity(0, set(range(16, 32)))
    os.environ['LC_ALL'] = 'C'
    arm = sys.argv[1]
    assert arm in ('pre', 'c4', 'post')
    scopes.BUILD.mkdir(parents=True, exist_ok=True)
    source = ROOT if arm == 'post' else BUILD / (arm + '-source')
    original = (ROOT / 'tests/climonfix5_scope.cc').read_text()
    start = original.index('    const std::string function=')
    end = original.index('    drive(frame({"FUNCTION"', start)
    replacement = ('    const std::string function="#!lua name=scope\\n"\n'
        '      "redis.register_function{function_name=\'scope\', callback=function(keys,args) "\n'
        '      "return {redis.call(\'GET\',keys[1]),redis.call(\'GET\',keys[2])} "\n'
        '      "end, flags={\'no-writes\'}}";\n')
    fixture = scopes.BUILD / 'readonly-scope.cc'
    fixture.write_text(original[:start] + replacement + original[end:])
    record = dict(arm=arm, source_commit=COMMITS.get(arm, 'e4a0e13ab'),
                  fixture_base_sha256=hashlib.sha256(original.encode()).hexdigest(),
                  replacement_before=original[start:end], replacement_after=replacement,
                  fixture_sha256=scopes.sha(fixture))
    if arm != 'post':
        source.mkdir(exist_ok=True)
        archive = subprocess.check_output(['git', 'archive', COMMITS[arm], 'src',
            'third_party', 'Makefile', 'tools/assert_map.py'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(source, filter='data')
        record['archive_sha256'] = hashlib.sha256(archive).hexdigest()
        with (DOC / ('readonly-' + arm + '-production-build.log')).open('w') as log:
            subprocess.run(['make', '-j16', 'all'], cwd=source, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        subprocess.run(['make', '-q', 'all'], cwd=source, check=True)
        expected = json.loads((DOC / 'arms.json').read_text())[arm.upper()]['sha256']
        record['rebuilt_binary_sha256'] = scopes.sha(source / 'build/tomokv')
        assert record['rebuilt_binary_sha256'] == expected
    scopes.save(DOC / ('readonly-' + arm + '-source.json'), record)
    objects = source / 'build'
    for ns in ('normal', 'db0'):
        dest = scopes.BUILD / (arm + '-' + ns + '-readonly')
        dest.mkdir(exist_ok=True)
        recipe = subprocess.check_output(['make', '-C', str(source), 'BUILD_ROOT=' + str(objects),
            '-n', '-W', str(objects / 'src/main.o'), 'all'], text=True)
        link = shlex.split(next(s for s in recipe.splitlines()
                                if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
        command = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
                   '-DTOMO_JEMALLOC', '-I' + str(source)]
        if ns == 'db0': command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        command += ['-c', str(fixture), '-o', str(dest / 'probe.o')]
        rename = ['objcopy', '--redefine-sym', 'main=scope_original_main',
                  str(objects / 'db0/src/main.o'), str(dest / 'original-main.o')]
        link = [str(dest / 'original-main.o') if x == str(objects / 'db0/src/main.o') else x for x in link]
        link += [str(dest / 'probe.o')]
        link[link.index('-o') + 1] = str(dest / 'probe')
        with (DOC / 'scopes' / (dest.name + '-build.log')).open('w') as log:
            for cmd in (command, rename, link):
                subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        scopes.save(DOC / 'scopes' / (dest.name + '-build.json'),
                    dict(compile=command, rename=rename, link=link, sha256=scopes.sha(dest / 'probe')))
    subprocess.run(['gcc', '-O2', str(DOC / 'step.c'), '-o', str(scopes.BUILD / 'step')], check=True)
    prepared = {(arm, ns): scopes.prepare(arm, ns, 'readonly') for ns in ('normal', 'db0')}
    cases = [(arm, ns, 'FCALL-header-' + shard, mode, batch, 1)
             for ns in ('normal', 'db0') for shard in ('single', 'cross')
             for mode in ('1s', '2s') for batch in (1, 32)]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda case: scopes.run(case, prepared, 'readonly'), cases))
    scopes.save(DOC / 'scopes' / ('readonly-results-' + arm + '.json'), rows)
    # Hashes, complete symbol counts and fixture substitutions are durable now.
    for ns in ('normal', 'db0'):
        shutil.rmtree(scopes.BUILD / (arm + '-' + ns + '-readonly'))
    if arm != 'post': shutil.rmtree(source)
    print(arm, 'readonly scopes complete; superseded sources and probes pruned', flush=True)


if __name__ == '__main__':
    main()
