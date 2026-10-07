#!/usr/bin/env python3
"""Offline PAD A: PRE behavior, POST cold DatabaseMap::State layout and .text size."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from lbstall_artifacts import Elf


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index('.text')][5]


def state_layout(path):
    code = ('import gdb,json; out={}; exec(' + repr(
        'for ns in ("tomo", "tomo_db0"):\n'
        ' t=gdb.lookup_type(ns+"::DatabaseMap::State")\n'
        ' out[ns]={"size":t.sizeof,"fields":{f.name:f.bitpos for f in t.fields() if f.name and hasattr(f,"bitpos")}}'
    ) + '); print(json.dumps(out,sort_keys=True))')
    return json.loads(subprocess.check_output(['gdb', '-nx', '-batch', str(path),
                                               '-ex', 'python ' + code], text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('build/shutsave'))
    args = parser.parse_args()
    root = args.root
    pre, post, pad = (root / name for name in ('PRE', 'POST', 'PAD'))
    pad.mkdir(exist_ok=True)
    for directory in ('src', 'db0'):
        shutil.copytree(pre / directory, pad / directory, dirs_exist_ok=True)
    commit = (pre / 'commit').read_text().strip()
    source = subprocess.check_output(['git', 'show', commit + ':src/cmd/multidb.cc'], text=True)
    marker = '    std::atomic<uint32_t> exited{0};\n'
    assert source.count(marker) == 1
    source = source.replace(marker, marker + '    std::atomic<uint64_t> persistence_seen_ms{0};\n')
    source_path = pad / 'multidb.cc'
    source_path.write_text(source)
    flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-DTOMO_JEMALLOC', '-Isrc/cmd', '-I.']
    for database, defines in (('', []), ('db0/', ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'])):
        subprocess.run([*flags, *defines, '-c', str(source_path), '-o',
                        str(pad / (database + 'src/cmd/multidb.o'))], check=True)
    objects = subprocess.check_output([
        'make', '--no-print-directory', '-s', 'BUILD_ROOT=' + str(pad),
        '--eval=shutsave-pad-list:;@echo $(DB0_OBJ) $(OBJ)', 'shutsave-pad-list'], text=True).split()
    wanted = text_size(post / 'tomokv')
    padding = 0
    for _ in range(3):
        (pad / 'padding.S').write_text(
            '.text\n.globl tomo_shutsave_pad\n.type tomo_shutsave_pad,@function\n'
            'tomo_shutsave_pad:\n.fill %d,1,0x90\n' % padding +
            '.size tomo_shutsave_pad,.-tomo_shutsave_pad\n.section .note.GNU-stack,"",@progbits\n')
        subprocess.run(['g++', '-c', str(pad / 'padding.S'), '-o', str(pad / 'padding.o')], check=True)
        subprocess.run(['g++', '-pthread', *objects, str(pad / 'padding.o'), '-o',
                        str(pad / 'tomokv'), '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm'], check=True)
        actual = text_size(pad / 'tomokv')
        if actual == wanted:
            break
        padding += wanted - actual
        assert padding >= 0, 'PAD behavior twin already exceeds POST text size'
    assert actual == wanted, (actual, wanted)
    layouts = {name: state_layout(root / name / 'tomokv') for name in ('PRE', 'POST', 'PAD')}
    assert layouts['PAD'] == layouts['POST'], 'PAD must carry the actual candidate cold layout'
    report = dict(kind='A: behaviour twin', behavior='PRE',
                  layout='POST cold DatabaseMap::State and total .text size; function addresses may differ',
                  padding_bytes=padding, text_bytes=wanted, state_layouts=layouts,
                  sha256=hashlib.sha256((pad / 'tomokv').read_bytes()).hexdigest())
    (pad / 'kind.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
