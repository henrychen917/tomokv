#!/usr/bin/env python3
"""Full disposable build that parks one committer after loading drawn.

This is a correctness control, never a performance arm. No production hook or
runtime option is added. All source and objects stay below this worktree/build.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

HOOK = '''
        if (const char* park = std::getenv("TOMO_PUBLISH_PARK")) {
            static std::atomic<bool> once{false};
            bool expected = false;
            if (::access(park, F_OK) == 0 && once.compare_exchange_strong(expected, true)) {
                const int fd = ::open((std::string(park) + ".entered").c_str(),
                                      O_CREAT | O_WRONLY, 0644);
                if (fd < 0) std::abort();
                ::close(fd);
                while (::access(park, F_OK) == 0) std::this_thread::yield();
            }
        }
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('.'))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = a.output.resolve()
    assert output.is_relative_to(root / 'build')
    # Inherit the invoking lane's allocation; never move a build to another lane.
    cores = sorted(os.sched_getaffinity(0))
    assert cores
    source = output / 'source'
    source.mkdir(parents=True, exist_ok=False)
    for name in ('src', 'third_party'):
        shutil.copytree(a.source / name, source / name)
    shutil.copy2(a.source / 'Makefile', source / 'Makefile')
    map_tool = a.source / 'tools/assert_map.py'
    if map_tool.exists():  # Historical source trees predate assertion maps.
        (source / 'tools').mkdir()
        shutil.copy2(map_tool, source / 'tools/assert_map.py')
    header = source / 'src/core/server.h'
    text = header.read_text()
    anchor = '        const uint64_t drawn = commit_seq_.load(std::memory_order_seq_cst);'
    if anchor not in text:
        anchor = anchor.replace('const uint64_t', 'uint64_t')
    assert text.count(anchor) == 1
    text = text.replace('#pragma once', '#pragma once\n#include <fcntl.h>\n#include <thread>\n#include <unistd.h>')
    header.write_text(text.replace(anchor, anchor + '\n' + HOOK))
    argv = ['taskset', '-c', ','.join(map(str, cores)), 'make', f'-j{min(32, len(cores))}',
            f'BUILD_ROOT={output / "objects"}', 'all']
    (output / 'command.json').write_text(json.dumps(dict(argv=argv, cwd=str(source)), indent=2) + '\n')
    with (output / 'build.log').open('w') as log:
        subprocess.run(argv, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    shutil.copy2(output / 'objects/tomokv', output / 'tomokv')


if __name__ == '__main__':
    main()
