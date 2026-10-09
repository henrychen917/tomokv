#!/usr/bin/env python3
"""PAD B: sidecar behavior, padding restoring inline PRE's aggregate .text size."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'tools'))
from lbstall_artifacts import Elf

pre = root / 'build/deadswitch/ttl-inline/tomokv'
post = root / 'build/deadswitch/ttl-sidecar/tomokv'
out = root / 'build/deadswitch/ttl-pad-b'
out.mkdir(exist_ok=True)
binary = out / 'tomokv'

def text_size(path):
    e = Elf(path)
    return e.sections[e.names.index('.text')][5]

target = text_size(pre)
amount = target - text_size(post)
assert amount > 300, 'inverse size control is only justified by material shrinkage'
log = (root / 'build/deadswitch/06-sidecar-build.log').read_text()
command = next(shlex.split(line) for line in log.splitlines()
               if ' -o build/deadswitch/ttl-sidecar/tomokv ' in line)
index = command.index('-o')
command[index + 1] = str(binary)
command.insert(index, str(out / 'padding.o'))
properties = Elf(root / 'build/deadswitch/ttl-sidecar/src/main.o')
property_bytes = properties.section_data(properties.names.index('.note.gnu.property'))
(out / 'properties.bin').write_bytes(property_bytes)
for attempt in range(3):
    source = out / 'padding.s'
    source.write_text(f'.text\n.fill {amount}, 1, 0x90\n'
                      '.section .note.GNU-stack,"",@progbits\n'
                      '.section .note.gnu.property,"a",@note\n.p2align 3\n'
                      f'.incbin "{out / "properties.bin"}"\n')
    subprocess.run(['g++', '-c', str(source), '-o', str(out / 'padding.o')], check=True)
    subprocess.run(command, cwd=root, check=True)
    delta = target - text_size(binary)
    if not delta:
        break
    amount += delta
else:
    raise AssertionError('could not restore PRE text size')

a, b = Elf(post), Elf(binary)
assert a.section_data(a.names.index('.note.gnu.property')) == \
       b.section_data(b.names.index('.note.gnu.property')), 'preserve CET/ISA properties and PLT shape'
old, new = a.functions(), b.functions()
text_index = a.names.index('.text')
in_text = {n: s for n, s in old.items() if s['sec'] == text_index}
assert in_text and all(n in new and (s['value'], s['size']) ==
                      (new[n]['value'], new[n]['size']) for n, s in in_text.items())
padding = Elf(out / 'padding.o')
assert not padding.functions() and not padding.relocs
assert padding.section_data(padding.names.index('.text')) == b'\x90' * amount
objects = [Path(word) for word in command if word.endswith('.o') and word != str(out / 'padding.o')]
proof = dict(kind='B: inverse control; candidate sidecar behavior plus padding restoring PRE text size',
             limitation='Controls aggregate text size, not every PRE hot-function address or alignment.',
             pre_text=target, post_text=text_size(post), pad_text=text_size(binary),
             nop_bytes=amount, preserved_post_text_functions=len(in_text), command=command,
             production_objects={str(p): hashlib.sha256((root / p).read_bytes()).hexdigest() for p in objects},
             binaries={str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (pre, post, binary)})
(root / 'docs/deadswitch/06-pad-b.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps({k:v for k,v in proof.items() if k not in ('command','production_objects')}, indent=2))
