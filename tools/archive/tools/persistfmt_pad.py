#!/usr/bin/env python3
"""Build PAD-A: PRE persistence behavior, POST headers and total .text size.

This creates an isolated build-only source copy. No runtime switch enters the
production binary. Unreachable NOPs equalize .text size; internal function
addresses are not claimed identical. Run under taskset -c 96-111.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'build/persistfmt/PAD-A'


def body(text, signature, replacement):
    start = text.index('{', text.index(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[:start] + '{\n' + replacement + '\n}' + text[end:]


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def section_size(binary, section='.text'):
    output = subprocess.check_output(['readelf', '-SW', str(binary)], text=True)
    return int(re.search(r'\]\s+' + re.escape(section) + r'\s+PROGBITS\s+\S+\s+\S+\s+(\S+)', output)[1], 16)


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(96, 112))
    os.environ['LC_ALL'] = 'C'
    source = DEST / 'source'
    shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
    if not (source / 'third_party').exists():
        (source / 'third_party').symlink_to(ROOT / 'third_party', target_is_directory=True)
    p = source / 'src/cmd/serialize.cc'
    s = p.read_text().replace('if (type == Type::Stream) return encode_stream(native, out);',
                             'if (type == Type::Stream) return false;')
    s = s.replace('return decode_stream(body, rdb_type, decoded.payload);', 'return false;')
    s = s.replace('envelope.n < kDumpTrailerBytes)', 'envelope.n < kDumpTrailerBytes + 1)')
    p.write_text(s)
    p = source / 'src/cmd/functions.cc'
    s = body(p.read_text(), 'bool function_snapshot_save(', '    image.clear(); return true;')
    s = body(s, 'bool function_snapshot_load(', '    return true;')
    p.write_text(s)
    p = source / 'src/snapshot/snapshot.cc'
    s = p.read_text().replace('    bool save = true, flush = true, merge = false;',
        '    if (op.argc() != 2) {\n'
        '        reply_err(op.sink(), "ERR unknown subcommand or wrong number of arguments for \'debug\' command");\n'
        '        return false;\n    }\n'
        '    bool save = true, flush = true, merge = false;', 1)
    p.write_text(s)
    p = source / 'src/persist/aof.cc'
    s = p.read_text()
    a = s.index('void AofManager::fail(')
    b = s.index('\nbool AofManager::write_header_normal()', a)
    fail = s[a:b].replace('    recording_.store(false, std::memory_order_release);\n', '')
    fail = fail.replace('    std::fprintf(stderr, "AOF error:',
        '    recording_.store(false, std::memory_order_release);\n    std::fprintf(stderr, "AOF error:', 1)
    p.write_text(s[:a] + fail + s[b:])
    replacements = {}
    recipes = []
    def compile_one(item):
        namespace, unit = item
        obj = 'build/' + ('db0/' if namespace == 'db0' else '') + 'src/' + unit + '.o'
        relative = 'src/' + unit + '.cc'
        recipe = subprocess.check_output(['make', '-n', '-W', relative, obj], cwd=ROOT, text=True)
        cmd = shlex.split(next(x for x in recipe.splitlines() if ' -c ' + relative + ' ' in x))
        output = DEST / (namespace + '-' + unit.replace('/', '-') + '.o')
        cmd[cmd.index('-o') + 1] = str(output)
        # Dependency files are build artifacts, never writes into the main tree.
        with (output.with_suffix('.log')).open('w') as log:
            subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
        return obj, str(output), cmd
    items = [(n, u) for n in ('normal', 'db0')
             for u in ('cmd/serialize', 'cmd/functions', 'snapshot/snapshot', 'persist/aof')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for obj, output, cmd in pool.map(compile_one, items):
            replacements[obj] = output
            recipes.append(cmd)
    link = json.loads((ROOT / 'build/persistfmt/POST/link.json').read_text())
    link = [replacements.get(x, x) for x in link]
    binary = DEST / 'tomokv'
    link[link.index('-o') + 1] = str(binary)
    subprocess.run(link, cwd=ROOT, check=True)
    post = ROOT / 'build/persistfmt/POST/tomokv'
    wanted, unpadded = section_size(post), section_size(binary)
    assert wanted >= unpadded, (wanted, unpadded)
    padding = wanted - unpadded
    rodata_padding = section_size(post, '.rodata') - section_size(binary, '.rodata')
    assert rodata_padding >= 0, rodata_padding
    assembly = DEST / 'padding.S'
    assembly.write_text('.section .text\n.globl persistfmt_unreachable_padding\n'
                        '.type persistfmt_unreachable_padding,@function\n'
                        'persistfmt_unreachable_padding:\n'
                        f'.fill {padding},1,0x90\n'
                        '.size persistfmt_unreachable_padding,.-persistfmt_unreachable_padding\n'
                        f'.section .rodata\n.fill {rodata_padding},1,0\n'
                        '.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['gcc', '-c', str(assembly), '-o', str(DEST / 'padding.o')], check=True)
    link += [str(DEST / 'padding.o')]
    subprocess.run(link, cwd=ROOT, check=True)
    assert section_size(binary) == wanted
    assert section_size(binary, '.rodata') == section_size(post, '.rodata')
    report = dict(kind='A: behavior twin', post_sha256=sha(post), pad_sha256=sha(binary),
                  post_text=wanted, unpadded_text=unpadded, unreachable_padding=padding,
                  rodata_padding=rodata_padding,
                  recipes=recipes, link=link,
                  changed_sources={str(p.relative_to(source)): sha(p)
                                   for p in source.rglob('*.cc')
                                   if p.relative_to(source).as_posix() in
                                   ('src/cmd/serialize.cc', 'src/cmd/functions.cc',
                                    'src/snapshot/snapshot.cc', 'src/persist/aof.cc')})
    (ROOT / 'docs/persistfmt/pad-build.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('recipes', 'link')}))


if __name__ == '__main__':
    main()
