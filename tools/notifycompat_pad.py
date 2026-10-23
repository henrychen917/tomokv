#!/usr/bin/env python3
"""Kind A: full PRE behavior with POST's exact .text size, not function placement.

Relink the captured PRE inputs and first require the original PRE SHA. For a
smaller candidate, compile PRE's cold OBJECT/admin translation unit with -Os,
then append unreachable padding to match POST's exact total text size. All
other PRE objects are reused verbatim. This does not reproduce POST function
placement. A separate inverse B control retains POST placement and PRE size.
"""
from collections import Counter
import hashlib
import json
import os
import shlex
from pathlib import Path
import subprocess

from lbstall_artifacts import Elf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.sched_getaffinity(0) <= set(range(48, 64)), 'build only on lane CPUs'
    root = Path.cwd()
    pre, post = root / 'build/tomokv-pre', root / 'build/tomokv'
    output = root / 'build/tomokv-pad-a'
    directory = root / 'build/notifycompat/full-pad'
    directory.mkdir(parents=True, exist_ok=True)
    staged = directory / 'tomokv-pad-a.pending'
    cwd = root
    commands = [shlex.split(line) for line in
                (root / 'docs/notifycompat/build-pre.log').read_text().splitlines()
                if line.startswith('g++ ') and ' -o build/tomokv ' in line and ' -c ' not in line]
    assert len(commands) == 1
    command = [str(root / 'build/notifycompat-pre' / x.removeprefix('build/'))
               if x.startswith('build/') and x.endswith('.o') else x for x in commands[0]]
    destination = command.index('-o') + 1
    baseline = directory / 'baseline'
    command[destination] = str(baseline)
    subprocess.run(command, cwd=cwd, check=True)
    assert sha(baseline) == sha(pre), 'PRE link inputs changed'
    before, candidate = Elf(pre), Elf(post)
    pre_text = before.sections[before.names.index('.text')]
    post_text = candidate.sections[candidate.names.index('.text')]
    extra = post_text[5] - pre_text[5]
    compact = []
    if extra < 5:
        source_root = root / 'build/notifycompat-pre-proof'
        assert (source_root / 'src/cmd/server_tail.cc').read_bytes() == subprocess.check_output(
            ['git', 'show', 'ef5204b2e:src/cmd/server_tail.cc'])
        for namespace in ('src', 'db0/src'):
            rel = namespace + '/cmd/server_tail.o'
            lines = (root / 'docs/notifycompat/build-pre.log').read_text().splitlines()
            args, = [shlex.split(line) for line in lines if line.startswith('g++ ')
                     and ' -c ' in line and line.endswith('-o build/' + rel)]
            obj = directory / (namespace.replace('/', '_') + '-server_tail-os.o')
            args[args.index('-O2')] = '-Os'
            args[args.index('-o') + 1] = str(obj)
            subprocess.run(args, cwd=source_root, check=True)
            command[command.index(str(root / 'build/notifycompat-pre' / rel))] = str(obj)
            compact.append(dict(object=rel, command=args, cwd=str(source_root), sha256=sha(obj)))
        command[destination] = str(directory / 'compact-pre')
        subprocess.run(command, check=True)
        before = Elf(directory / 'compact-pre')
        extra = post_text[5] - before.sections[before.names.index('.text')][5]
    assert extra >= 5, 'cold PRE compression must leave room for exact-size padding'
    # An assembly input without the original GNU property note disables the
    # linker's IBT PLT and moves every function. Preserve the PRE feature note;
    # the unused function itself starts with ENDBR64 and uses an ordinary RET.
    note = before.sections[before.names.index('.note.gnu.property')]
    properties = before.data[note[4]:note[4] + note[5]]
    source, obj = directory / 'size_pad.S', directory / 'size_pad.o'
    source.write_text('.section .text.notifycompat_size_pad_a,"ax",@progbits\n'
                      '.balign 1\n.globl notifycompat_size_pad_a\n.hidden notifycompat_size_pad_a\n'
                      '.type notifycompat_size_pad_a,@function\nnotifycompat_size_pad_a:\nendbr64\nret\n'
                      f'.fill {extra - 5},1,0x90\n'
                      '.size notifycompat_size_pad_a,.-notifycompat_size_pad_a\n'
                      '.section .note.GNU-stack,"",@progbits\n'
                      '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' +
                      ','.join(hex(byte) for byte in properties) + '\n')
    subprocess.run(['g++', '-c', str(source), '-o', str(obj)], check=True)
    command[destination] = str(staged)
    command.insert(command.index('-o'), str(obj))
    subprocess.run(command, cwd=cwd, check=True)
    twin = Elf(staged)
    assert twin.sections[twin.names.index('.text')][5] == post_text[5]
    twin_note = twin.sections[twin.names.index('.note.gnu.property')]
    assert twin.data[twin_note[4]:twin_note[4] + twin_note[5]] == properties
    def functions(elf):
        section = elf.names.index('.text')
        return Counter((s['name'], s['value'], s['size']) for s in elf.symbols
                       if s['info'] & 15 == 2 and s['sec'] == section)
    old, new = functions(before), functions(twin)
    assert not old - new, 'an original PRE text function moved or changed size'
    added = list((new - old).elements())
    compact_text = before.sections[before.names.index('.text')]
    assert added == [('notifycompat_size_pad_a', compact_text[3] + compact_text[5], extra)], added
    inputs = [dict(path=x, sha256=sha(cwd / x)) for x in command
              if x.endswith('.o') and x != str(obj)]
    result = dict(kind='A: full PRE behavior with exact POST text size',
                  limitation='Total-text-size twin only; cold PRE server_tail uses -Os when needed; not POST function placement',
                  pre_sha256=sha(pre), post_sha256=sha(post), pad_sha256=sha(staged),
                  baseline_relink_identical=True, pre_text_bytes=pre_text[5],
                  post_text_bytes=post_text[5], pad_text_bytes=post_text[5],
                  padding_bytes=extra, original_text_symbols=sum(old.values()),
                  compact_pre_inputs=compact,
                  all_unpadded_twin_function_addresses_sizes_equal=True,
                  added_functions=added, source=source.read_text(),
                  command=command, cwd=str(cwd), output=str(output), inputs=inputs)
    staged.replace(output)
    (root / 'docs/notifycompat/pad-a.json').write_text(json.dumps(result, indent=2) + '\n')
    baseline.unlink()
    print(json.dumps({k:v for k,v in result.items() if k not in ('inputs','command','source')}, indent=2))
    # B: inverse control for the substantial text-size change. Reuse every POST
    # object and retain every POST function address, appending only unused text.
    if pre_text[5] - post_text[5] >= 5:
        extra = pre_text[5] - post_text[5]
        command = [str(root / x) if x.startswith('build/') and x.endswith('.o') else x
                   for x in commands[0]]
        command[command.index('-o') + 1] = str(root / 'build/tomokv-pad-b')
        source = directory / 'inverse_pad.S'
        source.write_text(result['source'].replace('notifycompat_size_pad_a', 'notifycompat_size_pad_b')
                          .replace(f'.fill {result["padding_bytes"] - 5}', f'.fill {extra - 5}'))
        obj = directory / 'inverse_pad.o'
        subprocess.run(['g++', '-c', str(source), '-o', str(obj)], check=True)
        command.insert(command.index('-o'), str(obj))
        subprocess.run(command, check=True)
        twin = Elf(root / 'build/tomokv-pad-b')
        assert twin.sections[twin.names.index('.text')][5] == pre_text[5]
        assert not functions(candidate) - functions(twin)
        (root / 'docs/notifycompat/pad-b.json').write_text(json.dumps(dict(
            kind='B: candidate behavior plus padding restoring PRE text size',
            post_sha256=sha(post), pad_sha256=sha(twin.path), text_bytes=pre_text[5],
            padding_bytes=extra, all_post_function_addresses_sizes_equal=True,
            command=command, source=source.read_text()), indent=2) + '\n')
    else:
        (root / 'build/tomokv-pad-b').unlink(missing_ok=True)
        (root / 'docs/notifycompat/pad-b.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
