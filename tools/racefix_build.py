#!/usr/bin/env python3
"""Copy production sources and insert the SV4.10 hook only in a witness build."""
import argparse
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    assert output.is_relative_to(root / 'build'), 'witness sources must stay in this worktree/build'
    output.mkdir(parents=True, exist_ok=True)
    for directory in ('src', 'third_party'):
        shutil.copytree(root / directory, output / directory, dirs_exist_ok=True)
    (output / 'tests').mkdir(exist_ok=True)
    shutil.copy2(root / 'tests/racefix_hook.h', output / 'tests/racefix_hook.h')
    shutil.copy2(root / 'Makefile', output / 'Makefile')
    server = output / 'src/core/server.h'
    text = server.read_text()
    anchor = '        climon_armed_.store(armed, std::memory_order_release);'
    assert text.count(anchor) == 1, 'refresh store anchor changed; review the witness'
    text = text.replace(anchor, '        if (racefix_test::before_store(armed)) return;\n' +
                        anchor + '\n        racefix_test::after_store(armed);')
    text = text.replace('namespace tomo {', '#include "tests/racefix_hook.h"\n\nnamespace tomo {', 1)
    server.write_text(text)
    debug = output / 'src/cmd/t_server.cc'
    text = debug.read_text()
    anchor = 'void cmd_debug_impl(Shard& shard, Op& op) {'
    assert text.count(anchor) == 1, 'DEBUG entry changed; review the witness'
    text = text.replace(anchor, anchor + '''
    if (op.arg(1).eq_icase("racefix-climon")) {
        if (!g_server || !g_thread) { reply_err(op.sink(), "ERR no context"); return; }
        racefix_test::command(*g_server, g_thread->id(), op);
        return;
    }''')
    debug.write_text(text)


if __name__ == '__main__':
    main()
