#!/usr/bin/env python3
"""Kind A: full PRE behavior with POST's exact .text size, not function placement.

Relink the captured PRE inputs and first require the original PRE SHA. Then
append an unreachable return/NOP function. Every original text function retains
its PRE address and size. This controls total text size; the separate WB twin
controls exact POST placement for the deferred-work change.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess

from lbstall_artifacts import Elf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.sched_getaffinity(0) <= set(range(80, 96)), 'build only on lane CPUs'
    root = Path.cwd()
    pre, post = root / 'build/tomokv-pre', root / 'build/tomokv'
    output = root / 'build/tomokv-pad-a'
    directory = root / 'build/iofix/full-pad'
    directory.mkdir(parents=True, exist_ok=True)
    receipt = json.loads((root / 'docs/iofix/pre-map-receipt.json').read_text())
    cwd = Path(receipt['cwd'])
    command = [x for x in receipt['command'] if not x.startswith('-Wl,-Map=')]
    destination = command.index('-o') + 1
    baseline = directory / 'baseline'
    command[destination] = str(baseline)
    subprocess.run(command, cwd=cwd, check=True)
    assert sha(baseline) == sha(pre) == receipt['pre_sha256'], 'PRE link inputs changed'
    before, candidate = Elf(pre), Elf(post)
    pre_text = before.sections[before.names.index('.text')]
    post_text = candidate.sections[candidate.names.index('.text')]
    extra = post_text[5] - pre_text[5]
    assert extra >= 5, 'this text-size control applies to a growing candidate'
    # An assembly input without the original GNU property note disables the
    # linker's IBT PLT and moves every function. Preserve the PRE feature note;
    # the unused function itself starts with ENDBR64 and uses an ordinary RET.
    note = before.sections[before.names.index('.note.gnu.property')]
    properties = before.data[note[4]:note[4] + note[5]]
    source, obj = directory / 'size_pad.S', directory / 'size_pad.o'
    source.write_text('.section .text.iofix_size_pad_a,"ax",@progbits\n'
                      '.balign 1\n.globl iofix_size_pad_a\n.hidden iofix_size_pad_a\n'
                      '.type iofix_size_pad_a,@function\niofix_size_pad_a:\nendbr64\nret\n'
                      f'.fill {extra - 5},1,0x90\n'
                      '.size iofix_size_pad_a,.-iofix_size_pad_a\n'
                      '.section .note.GNU-stack,"",@progbits\n'
                      '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' +
                      ','.join(hex(byte) for byte in properties) + '\n')
    subprocess.run(['g++', '-c', str(source), '-o', str(obj)], check=True)
    command[destination] = str(output)
    command.insert(command.index('-o'), str(obj))
    subprocess.run(command, cwd=cwd, check=True)
    twin = Elf(output)
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
    assert added == [('iofix_size_pad_a', pre_text[3] + pre_text[5], extra)], added
    inputs = [dict(path=x, sha256=sha(cwd / x)) for x in command
              if x.endswith('.o') and x != str(obj)]
    result = dict(kind='A: full PRE behavior with exact POST text size',
                  limitation='PRE function addresses retained; not POST function placement',
                  pre_sha256=sha(pre), post_sha256=sha(post), pad_sha256=sha(output),
                  baseline_relink_identical=True, pre_text_bytes=pre_text[5],
                  post_text_bytes=post_text[5], pad_text_bytes=post_text[5],
                  padding_bytes=extra, original_text_symbols=sum(old.values()),
                  all_original_function_addresses_sizes_equal=True,
                  added_functions=added, source=source.read_text(),
                  command=command, cwd=str(cwd), inputs=inputs)
    (root / 'docs/iofix/pad-a.json').write_text(json.dumps(result, indent=2) + '\n')
    baseline.unlink()
    print(json.dumps({k:v for k,v in result.items() if k not in ('inputs','command','source')}, indent=2))


if __name__ == '__main__':
    main()
