"""PAD-A: PRE behaviour with POST total .text size, not per-function placement."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf


def size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index('.text')][5]


pre, post, pad = (ROOT / 'build' / name for name in
                  ('tomokv-PRE', 'tomokv', 'tomokv-PAD-A'))
gap = size(post) - size(pre)
assert gap > 0, gap
base = ROOT / 'build/fliplisten/pad'
base.mkdir(exist_ok=True)
source, obj = base / 'pad.cc', base / 'pad.o'
source.write_text('asm(R"(.pushsection .text.fliplisten_pad,"ax",@progbits\n.fill '
                  + str(gap) + ',1,0x90\n.popsection\n)");\n')
subprocess.run(['g++', '-std=c++20', '-O2', '-g', '-march=native', '-c',
                str(source), '-o', str(obj)], check=True)
link = shlex.split(next(line for line in reversed(
    (ROOT / 'docs/fliplisten/build-pre.log').read_text().splitlines())
    if line.startswith('g++ ') and ' -Wl,--wrap=main ' in line))
link[link.index('-o') + 1] = str(pad)
link.insert(link.index('-o'), str(obj))
subprocess.run(link, cwd=ROOT, check=True)
assert size(pad) == size(post), (size(pad), size(post))
receipt = dict(kind='A: behaviour twin', scope=__doc__, padding_bytes=gap,
               link_argv=link, arms={name: dict(path=str(path),
               sha256=hashlib.sha256(path.read_bytes()).hexdigest(), text_bytes=size(path))
               for name, path in [('PRE', pre), ('POST', post), ('PAD-A', pad)]})
(ROOT / 'docs/fliplisten/arms.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt['arms']), flush=True)
