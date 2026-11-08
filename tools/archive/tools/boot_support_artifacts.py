#!/usr/bin/env python3
"""Offline ELF audit and cleanup-boot PAD controls. Never executes a server ELF."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tarfile

from lbstall_artifacts import Elf
from flipsettle_artifacts import inventory, corrupt_control
from ttlstate_proof import compare_files, program_headers, relocations

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'build/cleanup-boot'


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def functions(e):
    # Include zero-size functions and repeated local names; a dict of one symbol
    # per name silently drops real addresses in a linked executable.
    result = {}
    for s in e.symbols:
        if s['info'] & 15 == 2 and 0 < s['sec'] < len(e.sections) and e.sections[s['sec']][2] & 4:
            result.setdefault(s['name'], []).append((s['value'], s['size'], e.names[s['sec']]))
    return {name: sorted(values) for name, values in result.items()}


def function_count(e):
    return sum(len(values) for values in functions(e).values())


def audit():
    rows = {}
    objects = sorted(p.relative_to(BASE / 'PRE') for tree in ('src', 'db0/src')
                     for p in (BASE / 'PRE' / tree).rglob('*.o') if p.is_file())
    assert len(objects) == 84
    for path in [Path('tomokv')] + objects:
        rows[str(path)] = compare_files(BASE / 'PRE' / path, BASE / 'POST' / path)
    save(BASE / 'identity.json', rows)
    print('Complete ELF identity:', sum(r['okay'] for r in rows.values()), '/', len(rows))
    # Keep every function from the four affected TUs, not a headline hot-symbol sample.
    bodies = []
    for tree in ('src', 'db0/src'):
        for unit in ('main', 'core/genthread', 'core/rl2s', 'core/reorder'):
            name = tree + '/' + unit + '.o'
            a, b = Elf(BASE / 'PRE' / name), Elf(BASE / 'POST' / name)
            fa, fb = a.functions(), b.functions()
            for symbol in sorted(fa.keys() | fb.keys()):
                left, right = fa.get(symbol), fb.get(symbol)
                raw = bool(left and right and a.body(left) == b.body(right))
                # Diagnostic only: normalized bytes NEVER confer byte identity.
                resolved = bool(left and right and a.canonical(left) == b.canonical(right))
                bodies.append(dict(object=name, symbol=symbol,
                    pre_size=left['size'] if left else None, post_size=right['size'] if right else None,
                    raw_bytes_equal=raw, bytes_and_resolved_targets_equal=resolved))
    save(BASE / 'all-runtime-functions.json', bodies)
    a, b = Elf(BASE / 'PRE/tomokv'), Elf(BASE / 'POST/tomokv')
    fa, fb = functions(a), functions(b)
    save(BASE / 'linked-functions.json', [dict(symbol=n, pre=fa.get(n), post=fb.get(n))
                                         for n in sorted(fa.keys() | fb.keys())])
    save(BASE / 'entry-and-mappings.json', {
        arm: dict(entry=struct.unpack_from('<Q', e.data, 24)[0], program_headers_hex=program_headers(e).hex())
        for arm, e in [('PRE', a), ('POST', b)]})
    for arm in ('PRE', 'POST'):
        # Raw relocation text complements the raw section dumps and resolved JSON.
        for name in rows:
            with (BASE / arm / 'proof' / name / 'readelf-relocations.txt').open('wb') as out:
                subprocess.run(['readelf', '-Wr', str(BASE / arm / name)], stdout=out, check=True)
    corrupt_control(BASE / 'PRE/tomokv', BASE / 'byte-negative-control')
    control = compare_files(BASE / 'PRE/tomokv',
                            BASE / 'byte-negative-control/one-executable-byte-changed.DO-NOT-RUN')
    assert not control['okay'] and any('executable .text: bytes differ' == e for e in control['errors'])
    save(BASE / 'byte-negative-control/complete-checker.json', control)
    changed = [r for r in bodies if not r['bytes_and_resolved_targets_equal']]
    print('All runtime functions:', len(bodies), '; differing bytes/targets or inventory:', len(changed))


def legacy_strings(source, destination):
    """Truncate ONLY the two appended banner suffixes, without moving a byte."""
    e = Elf(source)
    data = bytearray(e.data)
    index = e.names.index('.rodata')
    sec = e.sections[index]
    raw = e.section_data(index)
    patches = []
    for prefix in (b'tomokv-cpp: %u unified threads,', b'tomokv-cpp: %u threads (%zu io + %zu ex),'):
        starts = [i for i in range(len(raw)) if raw.startswith(prefix, i)]
        candidates = []
        for start in starts:
            end = raw.index(b'\0', start)
            text = raw[start:end]
            if text.endswith(b'alloc=%s, reorder=%d, read-local=%u\n'):
                candidates.append((start, text))
        assert len(candidates) == 1, (prefix, candidates)
        start, text = candidates[0]
        at = sec[4] + start + text.index(b', reorder=%d, read-local=%u\n', text.index(b'alloc=%s'))
        assert data[at:at + 2] == b', '
        data[at:at + 2] = b'\n\0'
        patches.append(dict(file_offset=at, before=text.decode(), after=text[:at - sec[4] - start].decode() + '\n'))
    shutil.copyfile(source, destination)
    destination.write_bytes(data)
    destination.chmod(source.stat().st_mode)
    return patches


def dump_binary(arm):
    directory = BASE / arm / 'proof/tomokv'
    directory.mkdir(parents=True, exist_ok=True)
    receipt = inventory(BASE / arm / 'tomokv', directory)
    save(BASE / arm / 'inventory.json', receipt)
    with (directory / 'readelf-relocations.txt').open('wb') as out:
        subprocess.run(['readelf', '-Wr', str(BASE / arm / 'tomokv')], stdout=out, check=True)
    (BASE / arm / 'SHA256SUMS').write_text(sha(BASE / arm / 'tomokv') + '  ' + str(BASE / arm / 'tomokv') + '\n')


def pad_a():
    out = BASE / 'PAD-A'
    out.mkdir(exist_ok=True)
    patches = legacy_strings(BASE / 'POST/tomokv', out / 'tomokv')
    a, b = Elf(BASE / 'POST/tomokv'), Elf(out / 'tomokv')
    assert functions(a) == functions(b), 'every function address and size must match POST'
    assert a.data[16:32] == b.data[16:32] and program_headers(a) == program_headers(b)
    assert relocations(a) == relocations(b)
    for index, section in enumerate(a.sections):
        if section[2] & 4:
            assert section == b.sections[index] and a.section_data(index) == b.section_data(index)
    changed = [i for i, (x, y) in enumerate(zip(a.data, b.data)) if x != y]
    assert changed == sorted(i for patch in patches for i in (patch['file_offset'], patch['file_offset'] + 1))
    save(out / 'layout.json', dict(kind='A: PRE behaviour with POST text size/layout',
         pre_sha256=sha(BASE / 'PRE/tomokv'), post_sha256=sha(BASE / 'POST/tomokv'),
         pad_sha256=sha(out / 'tomokv'), functions=function_count(a),
         every_function_address_and_size_equal=True, every_executable_byte_equal_to_post=True,
         entry_mappings_and_relocations_equal=True, patches=patches,
         scope='Only the reporting correction changes behaviour; factoring preserves the boot protocols. '
               'PAD restores the exact PRE banners. This is unrelated to the R7 capability PAD.'))
    dump_binary('PAD-A')
    print('PAD-A:', function_count(a), 'function addresses/sizes and all executable bytes match POST')


def pad_b():
    out = BASE / 'PAD-B'
    out.mkdir(exist_ok=True)
    pre, post = Elf(BASE / 'PRE/tomokv'), Elf(BASE / 'POST/tomokv')
    delta = pre.sections[pre.names.index('.text')][5] - post.sections[post.names.index('.text')][5]
    assert delta > 300, 'inverse control here is for a substantial text shrink'
    # An assembly object without the existing CET note disables .plt.sec at link
    # time and moves every function. Preserve the production input's exact note.
    note_source = Elf(BASE / 'POST/src/main.o')
    note = out / 'gnu-property.bin'
    note.write_bytes(note_source.section_data(note_source.names.index('.note.gnu.property')))
    assembly = out / 'restore-text-size.s'
    assembly.write_text('.section .text\n.fill ' + str(delta) + ',1,0x90\n'
                        '.section .note.GNU-stack,"",@progbits\n'
                        '.section .note.gnu.property,"a"\n.p2align 3\n.incbin "' + str(note) + '"\n')
    subprocess.run(['g++', '-c', str(assembly), '-o', str(out / 'padding.o')], check=True)
    commands = [shlex.split(line) for line in (BASE / 'PRE/build.log').read_text().splitlines()
                if line.startswith('g++ ') and ' -c ' not in line]
    command, = commands
    command = [str(BASE / 'POST' / c.removeprefix('build/')) if c.startswith('build/') and c.endswith('.o') else c
               for c in command]
    command[command.index('-o') + 1] = str(out / 'tomokv')
    command += [str(out / 'padding.o')]
    with (out / 'build.log').open('w') as log:
        log.write(shlex.join(command) + '\n'); log.flush()
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    twin = Elf(out / 'tomokv')
    assert twin.sections[twin.names.index('.text')][5] == pre.sections[pre.names.index('.text')][5]
    fp, ft = functions(post), functions(twin)
    differences = {name: dict(post=fp.get(name), pad=ft.get(name))
                   for name in fp.keys() | ft.keys() if fp.get(name) != ft.get(name)}
    save(out / 'function-differences.json', differences)
    assert set(differences) == {'_fini'}, f'{len(differences)} function layouts differ; see function-differences.json'
    assert ft['_fini'][0][0] - fp['_fini'][0][0] == delta
    save(out / 'layout.json', dict(kind='B: POST behaviour with padding restoring PRE .text size',
         post_sha256=sha(BASE / 'POST/tomokv'), pad_sha256=sha(out / 'tomokv'), padding_bytes=delta,
         text_bytes=twin.sections[twin.names.index('.text')][5],
         unchanged_function_addresses_and_sizes=function_count(post) - 1, differences=differences,
         limitation='Independent address audit, not a claim inferred from NOPs: every serving function '
                    'retains its POST address/size; _fini moves. Loaded data/RIP relocations may move. '
                    'This supplementary inverse size control does NOT restore PRE hot addresses; '
                    'PAD-A is the required exact POST-layout behaviour twin.'))
    dump_binary('PAD-B')
    print('PAD-B:', delta, 'bytes; all function addresses/sizes match POST except _fini')


def legacy_check():
    """Run only a formatter fixture, comparing PAD against extracted frozen PRE printf blocks."""
    out = BASE / 'PAD-A'
    with tarfile.open(BASE / 'frozen/reference.tar') as archive:
        blocks = []
        for name in ['src/core/genthread.cc', 'src/core/rl2s.cc', 'src/main.cc']:
            s = archive.extractfile(name).read().decode()
            start = s.index('    std::printf("tomokv-cpp:')
            end = s.index('    std::fflush(stdout);', start) + len('    std::fflush(stdout);')
            blocks.append(s[start:end].replace('std::printf(', 'std::fprintf(out, ').replace('std::fflush(stdout)', 'std::fflush(out)'))
    fixture = r'''
#include "tests/boot_support_checks.inc"
using namespace boot_support_checks;
void legacy(ResolvedState& srv, std::FILE* out) {
    const Config& cfg = srv.cfg(); const uint32_t nthreads = srv.nthreads();
    if (cfg.thread_mode == ThreadMode::Fused) { FUSED }
    else if (srv.read_local_enabled()) { LOCAL }
    else { SPLIT }
}
int main() {
    cpu_set_t cpuset; sched_getaffinity(0, sizeof(cpuset), &cpuset);
    std::string spec; unsigned cpus = 0;
    for (int c = 0; c < CPU_SETSIZE && cpus < 8; ++c) if (CPU_ISSET(c, &cpuset)) {
        if (cpus++) spec += ','; spec += std::to_string(c);
    }
    require(cpus == 8, "eight fixture CPUs"); Topology topo; require(topo.declare(spec.c_str()), "topology");
    unsigned cells = 0;
    for (auto mode : {ThreadMode::Fused, ThreadMode::Split})
    for (bool armed : {false, true}) for (unsigned requested : {0u, 1u})
    for (unsigned overlap : {0u, 1u}) for (int reorder : {0, 1})
    for (auto net : {NetIoEngine::Uring, NetIoEngine::Epoll})
    for (bool tcp : {false, true}) for (bool tls : {false, true}) for (bool unix_bound : {false, true}) {
        ResolvedState srv; srv.armed = armed; srv.config.thread_mode = mode; srv.config.shards = 16;
        srv.config.read_local = requested; srv.config.overlap = overlap;
        srv.config.reorder = reorder_for_mode(reorder, mode); srv.config.net_io = net;
        srv.config.port = tcp ? 16379 : 0; srv.config.tls_port = tls ? 16380 : 0;
        srv.config.unixsocket = unix_bound ? "/fixture.sock" : nullptr;
        bool fused = mode == ThreadMode::Fused;
        require(fused ? srv.placed.build_fused(topo, nullptr) : srv.placed.build_even(topo, 6, 2), "placement");
        for (unsigned tid = 0; tid < 8; ++tid) srv.workers[tid].owned.resize(fused ? 2 : tid < 6 ? 0 : 8);
        require(capture([&](std::FILE* f) { legacy(srv, f); }) ==
                capture([&](std::FILE* f) { print_boot_presentation(srv, f); }), "exact frozen PRE presentation");
        ++cells;
    }
    std::printf("PAD legacy presentation: %u exact PRE cells\n", cells);
}
'''
    for key, block in zip(('FUSED', 'LOCAL', 'SPLIT'), blocks): fixture = fixture.replace(key, block)
    (out / 'legacy-check.cc').write_text(fixture)
    subprocess.run(['g++', '-std=c++20', '-O2', '-pthread', '-I.', str(out / 'legacy-check.cc'),
                    '-o', str(out / 'format-POST')], cwd=ROOT, check=True)
    # Unpatched POST must fail the legacy check, proving the fixture sees the correction.
    result = subprocess.run([str(out / 'format-POST')], capture_output=True, text=True)
    assert result.returncode == 1 and 'exact frozen PRE presentation' in result.stderr
    legacy_strings(out / 'format-POST', out / 'format-PAD-A')
    result = subprocess.run([str(out / 'format-PAD-A')], capture_output=True, text=True, check=True)
    (out / 'legacy-check.log').write_text(result.stdout + result.stderr)
    print(result.stdout.strip())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('audit', 'pad-a', 'pad-b', 'legacy-check'))
    args = p.parse_args()
    {'audit': audit, 'pad-a': pad_a, 'pad-b': pad_b, 'legacy-check': legacy_check}[args.action]()
