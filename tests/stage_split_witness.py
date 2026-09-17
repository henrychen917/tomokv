#!/usr/bin/env python3
"""Serverless negative controls for the L3 storage witness; production sources stay intact."""
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from cache_l3_artifacts import Elf, link, slots_for, text_section, verify_layout, write_script


def matched_storage():
    # Exercise the custom linker script on the real finite MGET/MSET storage fixture,
    # including constructors, destructors, exceptions and allocator interposition.
    folder = ROOT / 'build/reb-l3/matched-unit'
    folder.mkdir(parents=True, exist_ok=True)
    compiler = ['g++']
    flags = ['-std=c++20', '-O1', '-g', '-pthread', '-ffunction-sections',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    libs = ['-Wl,--wrap=' + symbol for symbol in ('malloc', 'realloc', 'free', '_Znwm', '_Znam')]
    anchor = folder / 'imports.cc'
    anchor.write_text('#include <new>\n'
                      'void unused_array(void* p) { ::operator delete[](p, std::size_t(0)); }\n'
                      'void unused_scalar(void* p) { ::operator delete(p, std::size_t(0)); }\n')
    shared = folder / 'imports.o'
    subprocess.run(compiler + flags + ['-c', str(anchor), '-o', str(shared)], check=True)
    arms = {}
    for arm, include in (('post', ROOT), ('pad', ROOT / 'build/reb-l3/pre')):
        assert (include / 'src/exec/op.h').exists(), 'build tomokv-pad before this witness'
        obj = folder / f'{arm}.o'
        subprocess.run(compiler + flags + ['-I' + str(include), '-c',
                       str(ROOT / 'tests/stage_split_cost_unit.cc'), '-o', str(obj)], check=True)
        arms[arm] = [('imports.o', shared), ('fixture.o', obj)]
    slots, end = slots_for(arms)
    for arm in arms:
        script = folder / f'{arm}.ld'
        write_script(script, compiler, slots, end, arm)
        link(compiler, flags, libs, arms[arm], folder / arm, script)
    total = max(text_section(Elf(folder / arm))[5] for arm in arms)
    for arm in arms:
        script = folder / f'{arm}.ld'
        write_script(script, compiler, slots, end, arm, total)
        link(compiler, flags, libs, arms[arm], folder / arm, script)
    verify_layout(Elf(folder / 'post'), Elf(folder / 'pad'))
    for arm, size in (('post', 248), ('pad', 336)):
        run = subprocess.run([str(folder / arm)], capture_output=True, text=True, timeout=30)
        (folder / f'{arm}.log').write_text(run.stdout + run.stderr)
        assert run.returncode == 0 and f'"op_bytes":{size},' in run.stdout, (arm, run.stderr)
    # The audit must reject a different function placement, not merely unequal text size.
    moved = Elf(folder / 'post')
    symbol = next(s for s in moved.symbols if s['name'] == 'cache_l3_arg')
    symbol['value'] += 1
    try:
        verify_layout(moved, Elf(folder / 'pad'))
    except AssertionError as error:
        assert 'function placement differs' in str(error)
    else:
        raise AssertionError('layout verifier accepted a moved function')
    print('PASS matched layout: PRE/POST MGET/MSET ASAN/UBSAN fixtures; moved-function control rejected')


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'use taskset -c 112-127'
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    matched_storage()
    mutations = [
        ('alias-reply-homes', 'exec/op.h',
         'ops[i].reply.bind_inline(reply_bytes[i])',
         'ops[i].reply.bind_inline(reply_bytes[0])',
         'FAIL stage split: each slot owns its matching body'),
        ('eager-send-body', 'net/conn.h',
         'std::unique_ptr<SendState> send_state_;',
         'std::unique_ptr<SendState> send_state_ = std::make_unique<SendState>();',
         'FAIL stage split: an idle connection allocates no send body'),
    ]
    for name, header, before, after, failure in mutations:
        folder = ROOT / 'build/reb-l3/negative' / name
        shutil.copytree(ROOT / 'src', folder / 'src', dirs_exist_ok=True)
        path = folder / 'src' / header
        source = path.read_text()
        assert source.count(before) == 1, f'mutation no longer applies: {name}'
        path.write_text(source.replace(before, after))
        binary = folder / 'witness'
        with (folder / 'build.log').open('w') as log:
            subprocess.run([
                'g++', '-std=c++20', '-O1', '-g', '-pthread',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                '-I' + str(folder), str(ROOT / 'tests/stage_split_unit.cc'),
                '-o', str(binary)], check=True, stdout=log, stderr=subprocess.STDOUT)
        run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
        (folder / 'run.log').write_text(run.stdout + run.stderr)
        assert run.returncode != 0 and failure in run.stderr, (name, run.returncode, run.stderr)
        print(f'PASS negative control {name}: witness rejected the broken storage ({run.returncode})')


if __name__ == '__main__':
    main()
