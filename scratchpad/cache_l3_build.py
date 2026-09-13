#!/usr/bin/env python3
"""Frozen F11 decomposition and storage controls. Only compiles; never starts a server."""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/cache-L3-f11'
ARMS = OUT / 'arms'
# The shared Git store was lost during this lane's crash recovery. The original code commits
# (3aadb258e / 70c8f369c / fe5041604) survive as hashed source snapshots under build/, while this
# recovered commit retains the same implementation. Reconstruct fresh arms from reachable refs.
BASE = 'a363c2c5e'
POST = 'f5f521732'
CLEANUP = '1d2ce3940'
FLAGS = '-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread'

def run(args, cwd=ROOT, **kw):
    return subprocess.run(args, cwd=cwd, check=True, **kw)

def capture(args, cwd=ROOT):
    return run(args, cwd, stdout=subprocess.PIPE).stdout

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def snapshot(name, commit):
    dst = ARMS / name
    dst.mkdir(parents=True)
    archive = capture(['git', 'archive', commit, 'Makefile', 'src', 'third_party'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
        contents.extractall(dst, filter='data')
    return dst

def replace(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f'{path}: expected one occurrence of {old[:80]!r}')
    path.write_text(text.replace(old, new))

def pad_op(dst):
    # Same total raw storage and one allocation as POST, without moving any original Op field.
    # The smaller POST header stride is the mechanism, and cannot also be a no-field-move control.
    path = dst / 'src/exec/op.h'
    replace(path, '}  // namespace tomo', '''template <size_t Count> struct OpChunk {
    Op ops[Count];
    unsigned char unused[Count * 8];
};
static_assert(sizeof(OpChunk<8>) == 2752);
}  // namespace tomo''')
    path = dst / 'src/net/rob.h'
    replace(path, 'delete[] chunks_[i]', 'delete chunks_[i]')
    replace(path, 'Op*& ch = chunks_[idx / kChunkOps];',
            'OpChunk<kChunkOps>*& ch = chunks_[idx / kChunkOps];')
    replace(path, 'ch = new Op[kChunkOps];', 'ch = new OpChunk<kChunkOps>;')
    replace(path, 'return &ch[idx % kChunkOps];', 'return &ch->ops[idx % kChunkOps];')
    replace(path, 'Op* chunks_[kChunks] = {};', 'OpChunk<kChunkOps>* chunks_[kChunks] = {};')

def pad_client(dst):
    # Old descriptors remain inline. The 8-byte owner pointer fits an existing alignment hole;
    # a lazy 56-byte unused allocation matches POST's 2040 total raw bytes after a segmented send.
    # No negative padding can match POST's *smaller* idle header while retaining all PRE fields.
    path = dst / 'src/net/conn.h'
    replace(path, '#include <limits>', '#include <limits>\n#include <memory>')
    replace(path, 'Session   session_;                 // 68..71', '''Session   session_;                 // 68..71
    struct SendPad { unsigned char unused[56] = {}; };
    std::unique_ptr<SendPad> send_pad_; // uses PRE's 56-byte hole; all original offsets stay fixed''')
    replace(path, 'uint32_t build_segment_iov(bool& has_borrow, uint32_t& bytes) {',
            '''uint32_t build_segment_iov(bool& has_borrow, uint32_t& bytes) {
        if (!send_pad_ && !segments_.empty()) send_pad_ = std::make_unique<SendPad>();''')

def sources(dst):
    paths = [dst / 'Makefile']
    for name in ('src', 'third_party'):
        paths.extend(p for p in (dst / name).rglob('*') if p.is_file())
    return {str(p.relative_to(dst)): sha(p) for p in sorted(paths)}

def verify_pre(manifest):
    # Recovery-era commit names in an old manifest may no longer resolve. Verify the actual
    # bytes against the owner's reachable baseline, with ONLY the confirmed counter-swap file
    # substituted. Reusing an intact frozen arm must not silently import a different floor.
    archive = capture(['git', 'archive', BASE, 'Makefile', 'src', 'third_party'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
        expected = {m.name: hashlib.sha256(contents.extractfile(m).read()).hexdigest()
                    for m in contents if m.isfile()}
    swap_file = 'src/core/thread.h'
    expected[swap_file] = hashlib.sha256(capture(['git', 'show', f'{POST}:{swap_file}'])).hexdigest()
    if manifest['sources']['pre'] != expected:
        raise RuntimeError('PRE is not a363c2c5e plus the confirmed ThreadCtx swap')
    return {'base': capture(['git', 'rev-parse', BASE]).decode().strip(),
            'changed_files': [swap_file], 'swap_file_sha256': expected[swap_file]}

def padding_source(count, note):
    # On this build every C++ object advertises IBT/SHSTK. An assembler object without that
    # note drops the AND property at link time, removes .plt.sec and changes ALL external-call
    # placement even when the requested pad is zero. Carry the source object's exact note;
    # do not force new linker features or assume the build host's default feature flags.
    return ('.section .text,"ax",@progbits\n' + f'.fill {count},1,0x90\n' +
            '.section .note.GNU-stack,"",@progbits\n' +
            '.section .note.gnu.property,"a",@note\n.p2align 3\n' +
            f'.incbin "{note}"\n')

def placement_controls(result, env):
    # Reuse candidate 1's unreachable front/tail padding control. A shrinking .text cannot be
    # matched by negative padding: pad the smaller arm back to the larger one, recording which
    # source it preserves. This changes no field, instruction on a called path, or data allocation.
    controls = {}
    for candidate in ('header', 'body', 'op', 'client', 'post'):
        small, large = sorted(('pre', candidate), key=lambda a: result[a]['text_bytes'])
        delta = result[large]['text_bytes'] - result[small]['text_bytes']
        dst = ARMS / small
        folder = OUT / f'place-{candidate}'
        folder.mkdir(exist_ok=True)
        binary = folder / 'tomokv'
        objects = capture(['make', '--no-print-directory', '-s',
            '--eval=cache_l3_objects: ; @echo $(OBJ)', 'cache_l3_objects'], cwd=dst).decode().strip()
        note = folder / 'source-note.bin'
        run(['objcopy', '--only-section=.note.gnu.property', '-O', 'binary',
             str(dst / objects.split()[0]), str(note)])

        def link(front, tail):
            for name, count in (('front', front), ('tail', tail)):
                asm = folder / f'{name}.S'
                asm.write_text(padding_source(count, note))
                run(['g++', '-c', str(asm), '-o', str(folder / f'{name}.o')])
            with (folder / 'link.log').open('a') as log:
                run(['make', '-j1', 'CXX=g++', 'JE=1', f'BIN={binary}',
                     f'OBJ={folder / "front.o"} {objects} {folder / "tail.o"}', 'all'],
                    cwd=dst, env=env, stdout=log, stderr=subprocess.STDOUT)
            text = folder / 'text.bin'
            run(['objcopy', '--only-section=.text', '-O', 'binary', str(binary), str(text)])
            return text.stat().st_size

        front = delta
        for _ in range(8):
            growth = link(front, 0) - result[small]['text_bytes']
            if growth <= delta: break
            next_front = max(0, front - (growth - delta))
            if next_front == front: raise RuntimeError('cannot match placement padding')
            front = next_front
        else:
            raise RuntimeError('placement padding did not converge')
        tail = delta - growth
        size = link(front, tail) if tail else result[small]['text_bytes'] + growth
        if size != result[large]['text_bytes']: raise RuntimeError('placement size mismatch')
        controls[candidate] = dict(binary=str(binary), sha256=sha(binary), text_bytes=size,
            source_arm=small, matched_size_arm=large, front_bytes=front, tail_bytes=tail,
            fields_moved=False,
            limitation='Executable size and placement sensitivity control; function addresses are not matched.')
    (OUT / 'placement-controls.json').write_text(json.dumps(controls, indent=2) + '\n')

def matched_placement_controls():
    # POST is SMALLER than PRE, so a PRE-only positive pad cannot match POST's original
    # .text. Give every arm the same tail budget, then move the SAME unchanged PRE objects
    # forward inside that budget for PAD. POST-shift repeats the displacement on the candidate.
    # This makes a real PRE/PAD comparison possible without shrinking or repacking PRE data.
    # Frozen measured binaries remain untouched. These are placement controls, not a claim that
    # equal section size reproduces the different internal addresses created by recompilation.
    if not set(os.sched_getaffinity(0)) <= set(range(112, 128)):
        raise RuntimeError('invoke with taskset -c 112-127')
    manifest = json.loads((OUT / 'source-manifest.json').read_text())
    provenance = json.loads((OUT / 'build-provenance.json').read_text())
    verify_pre(manifest)
    original = provenance['arms']
    env = dict(os.environ, CXXFLAGS=FLAGS)
    for key in ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES'): env.pop(key, None)
    folder = OUT / 'placement-v2'
    folder.mkdir(exist_ok=True)
    shift = abs(original['pre']['text_bytes'] - original['post']['text_bytes'])
    if shift == 0: raise RuntimeError('choose a displacement for equal-sized originals')
    target = (max(a['text_bytes'] for a in original.values()) + shift + 4095) // 4096 * 4096

    def code_symbols(binary):
        # Local symbols may have the same name in multiple TUs. Preserve every occurrence;
        # comparing a dictionary keyed only by name would silently miss some changed bodies.
        found = {}
        for line in capture(['nm', '-S', '--defined-only', '--format=posix', str(binary)]).decode().splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[1] in ('t', 'T', 'w', 'W'):
                found.setdefault(parts[0], []).append((int(parts[2], 16), int(parts[3], 16)))
        return {name: sorted(entries) for name, entries in found.items()}

    def text_size(binary):
        text = binary.parent / 'text.bin'
        run(['objcopy', '--only-section=.text', '-O', 'binary', str(binary), str(text)])
        return text.stat().st_size, sha(text)

    objects = {}
    object_hashes = {}
    symbols = {}
    notes = {}
    for name, arm in original.items():
        dst = ARMS / name
        if sources(dst) != manifest['sources'][name]: raise RuntimeError(f'{name}: source drift')
        if sha(Path(arm['binary'])) != arm['sha256']: raise RuntimeError(f'{name}: binary drift')
        paths = capture(['make', '--no-print-directory', '-s',
            '--eval=cache_l3_objects: ; @echo $(OBJ)', 'cache_l3_objects'], cwd=dst).decode().split()
        objects[name] = paths
        object_hashes[name] = {p: sha(dst / p) for p in paths}
        symbols[name] = code_symbols(arm['binary'])
        notes[name] = folder / f'{name}-source-note.bin'
        run(['objcopy', '--only-section=.note.gnu.property', '-O', 'binary',
             str(dst / paths[0]), str(notes[name])])
        if not notes[name].stat().st_size: raise RuntimeError(f'{name}: missing source feature note')

    def link(name, source, front, tail):
        dst = folder / name
        dst.mkdir(exist_ok=True)
        for side, count in (('front', front), ('tail', tail)):
            asm = dst / f'{side}.S'
            asm.write_text(padding_source(count, notes[source]))
            run(['g++', '-c', str(asm), '-o', str(dst / f'{side}.o')])
        binary = dst / 'tomokv'
        with (dst / 'link.log').open('a') as log:
            run(['make', '-j4', 'CXX=g++', 'JE=1', f'BIN={binary}',
                 f'OBJ={dst / "front.o"} {" ".join(objects[source])} {dst / "tail.o"}', 'all'],
                cwd=ARMS / source, env=env, stdout=log, stderr=subprocess.STDOUT)
        return binary, text_size(binary)

    result = {}
    # First reproduce the original instruction bytes with zero padding. This checks that the
    # surviving objects, flags and linker really reconstruct the measured executable.
    for source in original:
        binary, (size, digest) = link(f'verify-{source}', source, 0, 0)
        if (size, digest) != (original[source]['text_bytes'], original[source]['text_sha256']):
            raise RuntimeError(f'{source}: frozen objects do not reproduce measured .text')
        binary.unlink()  # the measured original is retained; the verification hash is below
        (binary.parent / 'text.bin').unlink()

    recipes = [(name, name, 0) for name in original]
    recipes += [('pad', 'pre', shift), ('post-shift', 'post', shift)]
    if 'cleanup' in original: recipes.append(('cleanup-shift', 'cleanup', shift))
    for name, source, front in recipes:
        binary, (size, _) = link(name, source, front, 0)
        tail = target - size
        if tail < 0: raise RuntimeError('padding budget too small')
        binary, (size, digest) = link(name, source, front, tail)
        if size != target: raise RuntimeError(f'{name}: .text size mismatch')
        after = code_symbols(binary)
        before = symbols[source]
        if after.keys() != before.keys(): raise RuntimeError(f'{name}: code symbol set changed')
        shifts = Counter()
        for symbol, entries in before.items():
            if len(entries) != len(after[symbol]): raise RuntimeError(f'{name}: duplicate symbol lost')
            for (old_addr, old_size), (new_addr, new_size) in zip(entries, after[symbol]):
                if old_size != new_size: raise RuntimeError(f'{name}: {symbol} body size changed')
                shifts[new_addr - old_addr] += 1
        result[name] = dict(binary=str(binary), sha256=sha(binary), source_arm=source,
            source_binary_sha256=original[source]['sha256'], text_bytes=size, text_sha256=digest,
            front_bytes=front, tail_bytes=tail, fields_moved=False,
            unchanged_object_count=len(objects[source]), unchanged_symbol_sizes=sum(shifts.values()),
            symbol_address_deltas=dict(sorted(shifts.items())))
        print(f'Ready placement-v2/{name}: {result[name]["sha256"]}', flush=True)

    # No make invocation may have silently rebuilt a production TU along the way.
    for source, hashes in object_hashes.items():
        if hashes != {p: sha(ARMS / source / p) for p in objects[source]}:
            raise RuntimeError(f'{source}: production objects changed while making controls')
        if sha(Path(original[source]['binary'])) != original[source]['sha256']:
            raise RuntimeError(f'{source}: measured binary was overwritten')
    (folder / 'manifest.json').write_text(json.dumps(dict(
        text_bytes=target, displacement=shift, measured=False,
        purpose='Equal-size placement controls; all original data layouts and allocation paths retained.',
        limitation='Internal PRE/POST function addresses differ; a flat PAD alone cannot prove causation.',
        affinity=sorted(os.sched_getaffinity(0)), make_jobs=4,
        source_manifest_sha256=sha(OUT / 'source-manifest.json'),
        zero_padding_text_reproduction={n: a['text_sha256'] for n, a in original.items()},
        source_object_sha256=object_hashes, arms=result), indent=2) + '\n')
    (folder / 'SHA256SUMS').write_text(''.join(
        f'{arm["sha256"]}  {name}/tomokv\n' for name, arm in result.items()))

def cleanup_arm():
    # A one-method revision of the MEASURED POST, not a new floor or a compound redesign.
    # Keep the original post/ binary and source hashes intact so POST -> cleanup prices just
    # the unnecessary home-capacity reset on argv-triggered retirement.
    if not set(os.sched_getaffinity(0)) <= set(range(112, 128)):
        raise RuntimeError('invoke with taskset -c 112-127')
    manifest = json.loads((OUT / 'source-manifest.json').read_text())
    provenance = json.loads((OUT / 'build-provenance.json').read_text())
    verify_pre(manifest)
    expected = dict(manifest['sources']['post'])
    original = (ARMS / 'post/src/exec/op.h').read_text()
    revision = capture(['git', 'show', f'{CLEANUP}:src/exec/op.h']).decode()
    start, end = '    void shrink_to_inline() {', '    char* reserve(size_t n) {'
    old_method = original[original.index(start):original.index(end)]
    new_method = revision[revision.index(start):revision.index(end)]
    modified = original.replace(old_method, new_method)
    expected['src/exec/op.h'] = hashlib.sha256(modified.encode()).hexdigest()
    dst = ARMS / 'cleanup'
    if sources(ARMS / 'post') != manifest['sources']['post']:
        raise RuntimeError('measured POST source drift')
    if 'cleanup' not in manifest['sources']:
        # The recovered Git commit differs in comments/Makefile from the original hashed
        # snapshot. Use those verified measured bytes, not a near-equivalent recovery archive.
        for name in expected:
            (dst / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ARMS / 'post' / name, dst / name)
        (dst / 'src/exec/op.h').write_text(modified)
    if sources(dst) != expected: raise RuntimeError('cleanup differs by more than the named method')
    manifest['sources']['cleanup'] = expected
    manifest['cleanup_change_commit'] = capture(['git', 'rev-parse', CLEANUP]).decode().strip()
    (OUT / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    env = dict(os.environ, CXXFLAGS=FLAGS)
    for key in ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES'): env.pop(key, None)
    with (OUT / 'cleanup-build.log').open('a') as log:
        run(['make', '-j4', 'CXX=g++', 'JE=1', 'all'], cwd=dst, env=env,
            stdout=log, stderr=subprocess.STDOUT)
    binary = dst / 'build/tomokv'
    text = OUT / 'cleanup.text'
    run(['objcopy', '--only-section=.text', '-O', 'binary', str(binary), str(text)])
    arm = dict(binary=str(binary), sha256=sha(binary), text_bytes=text.stat().st_size,
               text_sha256=sha(text))
    provenance['arms']['cleanup'] = arm
    provenance['source_manifest_sha256'] = sha(OUT / 'source-manifest.json')
    provenance['cleanup_change_commit'] = manifest['cleanup_change_commit']
    (OUT / 'build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'Ready cleanup: {arm["sha256"]}', flush=True)
    matched_placement_controls()

def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    ARMS.mkdir(exist_ok=False)
    pre = snapshot('pre', BASE)
    post = snapshot('post', POST)
    floor = ('src/core/thread.h',)
    op_files = ('src/exec/op.h', 'src/net/rob.h')
    for name in floor:
        shutil.copy2(post / name, pre / name)
    op = snapshot('op', BASE)
    for name in floor + op_files:
        shutil.copy2(post / name, op / name)
    client = snapshot('client', BASE)
    for name in floor:
        shutil.copy2(post / name, client / name)
    for name in ('src/net/conn.h', 'src/cmd/t_server.cc'):
        shutil.copy2(post / name, client / name)
    for name in ('pad-op', 'pad-client', 'pad-post'):
        dst = snapshot(name, BASE)
        for filename in floor:
            shutil.copy2(post / filename, dst / filename)
        if name in ('pad-op', 'pad-post'): pad_op(dst)
        if name in ('pad-client', 'pad-post'): pad_client(dst)

    # Expose the argv-header permutation separately from moving reply bytes, so the whole
    # Op result cannot quietly attribute candidate 2's benefit to the F11 body mechanism.
    header = snapshot('header', BASE)
    for name in floor:
        shutil.copy2(post / name, header / name)
    fields = '''    Slice*   argv_heap_ = nullptr;
    uint32_t argv_cap_  = 0;
    uint32_t argc_      = 0;
'''
    replace(header / 'src/exec/op.h', fields, '')
    replace(header / 'src/exec/op.h', '    SmallBuf<kInlineReply> reply;',
            'private:\n' + fields + 'public:\n    SmallBuf<kInlineReply> reply;')
    body = snapshot('body', BASE)
    for name in floor + op_files:
        shutil.copy2(post / name, body / name)
    group = '''private:
    // Parse and execute both inspect argc/heap even for two inline arguments. Keeping that
    // metadata beside routing avoids fetching the tail solely to discover there is no heap.
    Slice*   argv_heap_ = nullptr;
    uint32_t argv_cap_  = 0;
    uint32_t argc_      = 0;
public:
'''
    replace(body / 'src/exec/op.h', group, '')
    replace(body / 'src/exec/op.h', '    Slice    argv_inline_[kInlineArgv];',
            '    Slice    argv_inline_[kInlineArgv];\n' + fields.rstrip())

    # Every binary is compiled from its archived sources. Never import root objects: their
    # timestamps do not establish which source/flags produced them after an interrupted build.
    manifest = {'base': BASE, 'post': POST, 'common_floor': list(floor),
                'sources': {p.name: sources(p) for p in sorted(ARMS.iterdir())}}
    (OUT / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Sources frozen; no server or measurement started.', flush=True)

def build():
    if not set(os.sched_getaffinity(0)) <= set(range(112, 128)):
        raise RuntimeError('invoke with taskset -c 112-127')
    manifest = json.loads((OUT / 'source-manifest.json').read_text())
    pre_verification = verify_pre(manifest)
    env = dict(os.environ, CXXFLAGS=FLAGS)
    for key in ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES'): env.pop(key, None)
    result = {}
    for name in ('pre', 'post', 'op', 'client', 'pad-op', 'pad-client', 'pad-post', 'header', 'body'):
        dst = ARMS / name
        if sources(dst) != manifest['sources'][name]: raise RuntimeError(f'{name}: source drift')
        print(f'Building {name}', flush=True)
        with (OUT / f'{name}-build.log').open('a') as log:
            run(['make', '-j4', 'CXX=g++', 'JE=1', 'all'], cwd=dst, env=env,
                stdout=log, stderr=subprocess.STDOUT)
        # A resumed build may need only the objects interrupted by ENOSPC. Inspect the
        # explicit recipe too: an incremental log need not mention an unchanged string TU.
        recipe = run(['make', '-n', '-B', 'CXX=g++', 'JE=1', 'build/src/cmd/t_string.o'],
                     cwd=dst, env=env, stdout=subprocess.PIPE).stdout.decode()
        (OUT / f'{name}-string-recipe.txt').write_text(recipe)
        if '--param large-unit-insns=10600' not in recipe:
            raise RuntimeError('missing string inline-budget evidence')
        binary = dst / 'build/tomokv'
        text = OUT / f'{name}.text'
        run(['objcopy', '--only-section=.text', '-O', 'binary', str(binary), str(text)])
        result[name] = {'binary': str(binary), 'sha256': sha(binary),
                        'text_bytes': text.stat().st_size, 'text_sha256': sha(text)}
        with (OUT / f'{name}-layout.txt').open('w') as log:
            command = ['gdb', '-q', '-nx', '-batch', str(binary)]
            for typ in ('Op', 'OpReply', 'Client', 'ThreadCtx', 'Shard', 'FlatStore',
                        'Rob<64>', 'AtomicEntry', 'Config'):
                command.extend(['-ex', f'p sizeof(tomo::{typ})'])
            command.extend(['-ex', 'ptype /o tomo::Op', '-ex', 'ptype /o tomo::Client',
                            '-ex', 'ptype /o tomo::ThreadCtx'])
            # PRE has no OpReply; GDB reports that absence and continues. No inferior is run.
            run(command, stdout=log, stderr=subprocess.STDOUT)
        (OUT / 'build-provenance.json').write_text(json.dumps({
            'compiler': capture(['g++', '--version']).decode().splitlines()[0],
            'cxxflags': FLAGS, 'affinity': sorted(os.sched_getaffinity(0)),
            'make_jobs': 4, 'pre_verification': pre_verification,
            'source_manifest_sha256': sha(OUT / 'source-manifest.json'),
            'measured': False, 'arms': result}, indent=2) + '\n')
        print(f'Ready {name}: {result[name]["sha256"]}', flush=True)
    placement_controls(result, env)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--placement-only', action='store_true',
                      help='relink verified frozen objects into equal-.text-size PRE/POST/PAD arms')
    mode.add_argument('--cleanup-only', action='store_true',
                      help='build the one-method cleanup revision and its equal-size controls')
    args = parser.parse_args()
    if args.cleanup_only:
        cleanup_arm()
    elif args.placement_only:
        matched_placement_controls()
    else:
        if not ARMS.exists(): prepare()
        build()
