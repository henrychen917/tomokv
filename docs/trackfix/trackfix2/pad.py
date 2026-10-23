"""PAD-A: PRE behaviour with POST total .text size, not per-function layout."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index('.text')][5]


pre, post, pad = [ROOT / ('build/' + name) for name in ('tomokv-PRE', 'tomokv', 'tomokv-PAD-A')]
gap = text_size(post) - text_size(pre)
assert gap >= 0, ('POST shrank; a different behaviour-twin construction is required', gap)
dest = ROOT / 'build/trackfix/trackfix2-pad'
dest.mkdir(parents=True, exist_ok=True)
source, obj = dest / 'pad.cc', dest / 'pad.o'
source.write_text('asm(R"(.pushsection .text.trackfix_pad,"ax",@progbits\n.fill ' +
                  str(gap) + ',1,0x90\n.popsection\n)");\n')
subprocess.run(['g++', '-std=c++20', '-O2', '-g', '-march=native', '-c', str(source), '-o', str(obj)], check=True)
lines = (ROOT / 'docs/trackfix/build-pre.log').read_text().splitlines()
link = shlex.split(next(line for line in reversed(lines) if line.startswith('g++ ') and ' -Wl,--wrap=main ' in line))
link = [str(ROOT / 'build/trackfix/pre-objects' / arg.removeprefix('build/'))
        if arg.startswith('build/') and arg.endswith('.o') else arg for arg in link]
link[link.index('-o') + 1] = str(pad)
link.insert(link.index('-o'), str(obj))
subprocess.run(link, cwd=ROOT, check=True)
assert text_size(pad) == text_size(post), (text_size(pad), text_size(post))
result = dict(kind='A: behaviour twin', scope=__doc__, padding_bytes=gap, link=link,
              arms={name: dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               text_bytes=text_size(path)) for name, path in
                    [('PRE', pre), ('POST', post), ('PAD-A', pad)]})
(ROOT / 'docs/trackfix/trackfix2/pad.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result['arms']), flush=True)
