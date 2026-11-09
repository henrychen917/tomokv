#!/usr/bin/env python3
"""Build disposable tornhold negative controls from production objects.

always-a extends the original bucket forever. old-priority omits hold acquisition
only in the generated priority parser. no-carry removes the scatter cut carry
from the directed parser unit. Source mutations live under build/; the
production parser, generated source, objects, and executable are never modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def planned(target, source=None):
    output = subprocess.check_output(['make', '-n', '-B', target], cwd=ROOT, text=True)
    commands = [shlex.split(line) for line in output.splitlines() if ' -o ' in line]
    if source:
        commands = [command for command in commands if '-c' in command and source in command]
    else:
        commands = [command for command in commands if '-c' not in command and
                    command[command.index('-o') + 1] == target]
    assert len(commands) == 1, (target, commands)
    return commands[0]


def run(command, folder, name):
    with (folder / (name + '.log')).open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('arm', choices=('always-a', 'old-priority', 'no-carry'))
    args = p.parse_args()
    folder = ROOT / 'build/tornhold/controls' / args.arm
    source = folder / 'source'
    source.mkdir(parents=True, exist_ok=True)
    # Real directory structure with symlinked leaves preserves quoted relative includes.
    for original in (ROOT / 'src').rglob('*'):
        destination = source / original.relative_to(ROOT)
        if original.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            destination.symlink_to(original)
    if args.arm == 'always-a':
        relative = Path('src/cmd/atomics_glue.inc')
        text = (ROOT / relative).read_text()
        before = 'if (hold.b_slot != PlainReadHold::kNone) {\n        bucket = 2;'
        after = 'if (hold.live()) {\n        bucket = 1;'
        unit = 'src/cmd/xshard.cc'
    elif args.arm == 'old-priority':
        relative = Path('src/core/reorder.cc')
        text = (ROOT / relative).read_text()
        begin = text.index('                if (__builtin_expect(!pass_hold, false) && rob.in_flight() != 0) {')
        end = text.index('                op->set_read_cut(pass_read_cut);', begin)
        before, after = text[begin:end], ''
        unit = 'src/core/reorder.cc'
    else:
        relative = Path('src/core/io_loop.h')
        text = (ROOT / relative).read_text()
        before = '                pass_read_cut = std::max(pass_read_cut, scatter_pool_.confirmed_snapshot_cut());\n'
        after = ''
    assert text.count(before) == 1
    mutated = source / relative
    mutated.unlink()
    mutated.write_text(text.replace(before, after))
    if args.arm == 'no-carry':
        command = planned('build/tornread-unit')
        command.insert(1, '-I' + str(source))
        binary = folder / 'unit'
        command[command.index('-o') + 1] = str(binary)
        run(command, folder, 'unit')
        (folder / 'receipt.json').write_text(json.dumps(dict(
            arm=args.arm, binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            changed_source=str(relative), commands=[command]), indent=2) + '\n')
        print(binary)
        return
    replacements = {}
    commands = []
    for variant in ('', 'db0/'):
        target = 'build/' + variant + unit.removesuffix('.cc') + '.o'
        output = folder / ('db0.o' if variant else 'normal.o')
        command = planned(target, unit)
        command[command.index(unit)] = str(source / unit)
        command[command.index('-o') + 1] = str(output)
        # Includes from sibling symlinked files still resolve into the source overlay.
        command.insert(1, '-I' + str(source))
        run(command, folder, 'compile-' + ('db0' if variant else 'normal'))
        commands.append(command)
        replacements[target] = str(output)
    command = planned('build/tomokv')
    command = [replacements.get(word, word) for word in command]
    binary = folder / 'tomokv'
    command[command.index('-o') + 1] = str(binary)
    run(command, folder, 'link'); commands.append(command)
    if args.arm == 'always-a':
        command = planned('build/tornread-unit')
        command = [replacements.get(word, word) for word in command]
        command[command.index('-o') + 1] = str(folder / 'unit')
        run(command, folder, 'unit'); commands.append(command)
    (folder / 'receipt.json').write_text(json.dumps(dict(
        arm=args.arm, binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        changed_source=str(relative), commands=commands), indent=2) + '\n')
    print(binary)


if __name__ == '__main__':
    main()
