#!/usr/bin/env python3
"""Offline/serverless SV1/SV2 controls and type-A layout twin. Never starts a server."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WRAP = '_ZN4tomo15SnapshotManager5startERNS_6ServerERNS_9ThreadCtxERNS_4RingEbRNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEPNS_10AofManagerEPKcSH_b'


def replace(path, old, new):
    data = path.read_text()
    assert data.count(old) == 1, (path, old)
    path.write_text(data.replace(old, new))


def old_save(path):
    replace(path, '''    const bool must_save = save == ShutdownSave::Save ||
        (save == ShutdownSave::Configured && save_schedule_armed());''',
        '    const bool must_save = save == ShutdownSave::Save;')


def old_signal(path):
    data = path.read_text()
    begin = data.index('    bool request_signal_shutdown() {')
    end = data.index('\n    }', begin)
    path.write_text(data[:begin] + '''    bool request_signal_shutdown() {
        return false; // throwaway PRE signal behavior''' + data[end:])


def make(args, directory, *targets):
    with (directory / 'build.log').open('a') as log:
        subprocess.run(['taskset', '-c', args.cores, 'make', '-j16', *targets], cwd=directory,
                       stdout=log, stderr=subprocess.STDOUT, check=True)


def controls(args):
    build = args.build_root.resolve()
    objects = sorted(p for p in (build / 'src').rglob('*.o') if p.name not in ('main.o', 'version.o'))
    assert objects and (build / 'shutdown-unit').exists()
    rows = []
    for defect, assertion in (
            ('command', 'default SHUTDOWN saves before stop'),
            ('signal', 'signal leaves owners alive for final save'),
            ('hold', 'held owner prevents admission of another snapshot'),
            ('completion', 'successful finalization publishes stop before releasing epoch'),
            ('no-save-signal', 'no-save signal stops without waiting for IO cron'),
            ('busy-bound', 'busy shutdown retry is bounded and preserves the running snapshot'),
            ('owner-bound', 'shutdown snapshot yields on stalled saving owner')):
        directory = ROOT / 'build' / ('climonfix-control-' + defect)
        directory.mkdir(exist_ok=True)
        shutil.copytree(ROOT / 'src', directory / 'src', dirs_exist_ok=True)
        shutil.copyfile(ROOT / 'tests/shutdown_unit.cc', directory / 'test.cc')
        obj = objects[:]
        source = 'test.cc'
        if defect == 'command':
            old_save(directory / 'src/cmd/server_tail.cc')
            obj.remove(build / 'src/cmd/server_tail.o')
            source = 'src/cmd/server_tail.cc'
            obj.insert(0, build / 'tests/shutdown_unit.o')
        elif defect in ('completion', 'owner-bound'):
            target = directory / 'src/snapshot/snapshot.cc'
            if defect == 'completion':
                replace(target, '    if (server_ && server_->shutdown_snapshot_active()) server_->finish_shutdown();\n', '')
            else:
                replace(target, '        if (!shutdown_deadline || now_ns() < shutdown_deadline) return false;',
                        '        return false; // throwaway unbounded shutdown wait')
            obj.remove(build / 'src/snapshot/snapshot.o')
            source = 'src/snapshot/snapshot.cc'
            obj.insert(0, build / 'tests/shutdown_unit.o')
        elif defect == 'signal':
            old_signal(directory / 'src/core/server.h')
        elif defect == 'no-save-signal':
            replace(directory / 'src/core/server.h',
                    '        if (!save_schedule_armed()) return false; // no save: wake/stop even a long-parked owner\n', '')
        elif defect == 'busy-bound':
            target = directory / 'src/cmd/server_tail.cc'
            replace(target, '''        if (now_ns() < signal_shutdown_deadline_ns_.load(std::memory_order_relaxed))
            return 0;''', '''        if (true)
            return 0;''')
            obj.remove(build / 'src/cmd/server_tail.o')
            source = 'src/cmd/server_tail.cc'
            obj.insert(0, build / 'tests/shutdown_unit.o')
        else:
            replace(directory / 'src/core/ex_loop.h', '''            if (!snapshot_was_cancelled_ && srv_->shutdown_snapshot_active()) {
                snapshot_owner_state_ = SnapshotOwnerState::ShutdownHeld;
                srv_->shutdown_snapshot_hold();
                snapshot_manager_->owner_finished(snapshot_epoch_);
                return 1;
            }
''', '')
        (directory / 'Makefile').write_text('''all: unit
unit: control.o
	g++ -pthread control.o ''' + ' '.join(map(str, obj)) + ''' -o $@ -ljemalloc -luring -lssl -lcrypto -lm -Wl,--wrap=clock_gettime -Wl,--wrap=''' + WRAP + '''
control.o: ''' + source + ''' $(wildcard src/*/*.h)
	g++ -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC -I. -c $< -o $@
''')
        make(args, directory)
        result = subprocess.run(['taskset', '-c', args.cores, str(directory / 'unit')],
                                capture_output=True, text=True, timeout=30)
        (directory / 'run.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 1 and assertion in result.stderr, (defect, result)
        print(defect + ': ' + result.stderr.strip())
        rows.append(dict(defect=defect, returncode=result.returncode, assertion=assertion))
    (ROOT / 'build/climonfix-controls.json').write_text(json.dumps(rows, indent=2) + '\n')


def pad(args):
    directory = ROOT / 'build/climonfix-pad-src'
    directory.mkdir(exist_ok=True)
    for name in ('src', 'third_party'):
        shutil.copytree(ROOT / name, directory / name, dirs_exist_ok=True)
    shutil.copyfile(ROOT / 'Makefile', directory / 'Makefile')
    # PRE membership/forwarding semantics with the candidate's two-word message and Server layout.
    replace(directory / 'src/core/climon_mask.h', 'return io >> 6;', 'return (io & 63) >> 6;')
    replace(directory / 'src/core/climon_mask.h',
            'high.load(std::memory_order_relaxed)', 'uint64_t{0}')
    old_save(directory / 'src/cmd/server_tail.cc')
    old_signal(directory / 'src/core/server.h')
    replace(directory / 'src/cmd/server_tail.cc', 'nullptr, nullptr, nullptr, true);',
            'nullptr, nullptr, nullptr, false);')
    replace(directory / 'src/cmd/server_tail.cc', '''        // The snapshot writer publishes stop before releasing the successful epoch''',
            '''        finish_shutdown(); // PRE explicit-SAVE shutdown
        // The snapshot writer publishes stop before releasing the successful epoch''')
    # Optional link-only nops match total .text bytes; this never adds an executed instruction.
    replace(directory / 'Makefile', '$(BIN): $(OBJ) $(DB0_OBJ)', '$(BIN): $(OBJ) $(DB0_OBJ) $(PAD_EXTRA)')
    replace(directory / 'Makefile', '$(DB0_OBJ) $(OBJ) -o $@', '$(DB0_OBJ) $(OBJ) $(PAD_EXTRA) -o $@')
    with (directory / 'Makefile').open('a') as out:
        out.write('\nbuild/pad-text.o: build/pad-text.S\n\t$(CXX) -c $< -o $@\n')
    make(args, directory)
    sys.path.insert(0, str(ROOT / 'tools'))
    from lbstall_artifacts import Elf
    def text_size(path):
        elf = Elf(path)
        return elf.sections[elf.names.index('.text')][5]
    post = args.build_root.resolve() / 'tomokv'
    binary = directory / 'build/tomokv'
    delta = text_size(post) - text_size(binary)
    assert delta >= 0, 'PAD is larger than POST: review before claiming a matched text-size twin'
    if delta:
        (directory / 'build/pad-text.S').write_text(
            '.text\n.space ' + str(delta) + ', 0x90\n.section .note.GNU-stack,"",@progbits\n')
        make(args, directory, 'PAD_EXTRA=build/pad-text.o')
    assert text_size(post) == text_size(binary), 'PAD .text size must match POST'
    output = ROOT / 'build/climonfix-pad'
    output.mkdir(exist_ok=True)
    shutil.copy2(binary, output / 'tomokv')
    (output / 'kind.json').write_text(json.dumps(dict(
        kind='A: PRE behavior with POST data layout and total text size',
        text_bytes=text_size(binary), unused_text_padding=delta,
        caveat='Individual function addresses differ; use the paired live null.'), indent=2) + '\n')
    print((output / 'kind.json').read_text())


def armed(args):
    sys.path.insert(0, str(ROOT / 'tools'))
    from lbstall_artifacts import Elf
    rows = []
    for variant in ('src', 'db0/src'):
        before = Elf(ROOT / 'build/climonfix-pre' / variant / 'cmd/climon.o')
        after = Elf(args.build_root.resolve() / variant / 'cmd/climon.o')
        def functions(elf):
            return {s['name']: s for s in elf.symbols
                    if '17climon_armed_gate' in s['name'] and not s['name'].endswith('.cold')}
        old, new = functions(before), functions(after)
        assert old.keys() == new.keys() and len(old) == 1
        for name in old:
            rows.append(dict(variant=variant, name=name, pre_size=old[name]['size'],
                             post_size=new[name]['size'],
                             identical=before.canonical(old[name]) == after.canonical(new[name])))
    assert all(row['identical'] for row in rows), rows
    (ROOT / 'build/climonfix-armed-audit.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('controls', 'pad', 'armed'))
    parser.add_argument('--cores', default='112-127')
    parser.add_argument('--build-root', type=Path, default=ROOT / 'build/climonfix-post')
    args = parser.parse_args()
    globals()[args.action](args)
