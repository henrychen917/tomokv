#!/usr/bin/env python3
"""Make a throwaway incidence observer source tree; never edit production code.

The supplied NT4 observer counts completed argv discarded by Incomplete. POST
subtracts only argv retained in the active frontier. The poisoned-header unit
independently establishes that retained arguments are not replayed. Counters are
not a throughput instrument, and both parser copies are observed.
"""
import argparse
from pathlib import Path
import shutil


COUNTERS = '''
struct alignas(64) PerfioReparseCount {
    std::atomic<uint64_t> incomplete{0}, arguments{0};
};
inline PerfioReparseCount perfio_reparse_counts[256];
inline void perfio_reparse_note(uint32_t owner, uint32_t arguments) {
    auto& c = perfio_reparse_counts[owner];
    c.incomplete.fetch_add(1, std::memory_order_relaxed);
    c.arguments.fetch_add(arguments, std::memory_order_relaxed);
}
inline std::string perfio_reparse_info() {
    uint64_t incomplete = 0, arguments = 0;
    for (auto& c : perfio_reparse_counts) {
        incomplete += c.incomplete.load(std::memory_order_relaxed);
        arguments += c.arguments.load(std::memory_order_relaxed);
    }
    return "perfio_incomplete:" + std::to_string(incomplete) + "\\r\\n" +
           "perfio_reparsed_arguments:" + std::to_string(arguments) + "\\r\\n";
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--post', action='store_true')
    args = ap.parse_args()
    assert not args.output.exists(), 'observer output must be fresh'
    shutil.copytree(args.source / 'src', args.output / 'src')
    shutil.copy2(args.source / 'Makefile', args.output / 'Makefile')
    p = args.output / 'src/net/resp.h'
    text = p.read_text().replace('#include <cstdint>', '#include <cstdint>\n#include <atomic>\n#include <string>')
    text = text.replace('enum class ParseResult { Ok, Incomplete, Error, Empty };',
                        'enum class ParseResult { Ok, Incomplete, Error, Empty };\n' + COUNTERS)
    p.write_text(text)
    for filename in ('src/core/io_loop.h', 'src/core/reorder.cc'):
        p = args.output / filename
        text = p.read_text()
        anchor = 'if (pr == ParseResult::Incomplete) {\n'
        assert text.count(anchor) == 1
        note = 'op->argc()'
        if args.post:
            # Insert after suspend_multibulk, so the exact production validity
            # tag participates. No constant-zero replacement is used.
            anchor = "if (pos < pass_rlen && pass_rbuf[pos] == '*') conn.suspend_multibulk();\n"
            assert text.count(anchor) == 1
            note += ' - (conn.multibulk_pending() ? std::min(op->argc(), conn.multibulk_frontier().completed) : 0)'
        text = text.replace(anchor, anchor + "                if (op->rbuf_off < pass_rlen && pass_rbuf[op->rbuf_off] == '*')\n" +
                            f'                    perfio_reparse_note(self_->id(), {note});\n')
        p.write_text(text)
    p = args.output / 'src/cmd/t_server.cc'
    text = p.read_text()
    anchor = 'void cmd_info(Shard&, Op& op) {\n    std::string body;'
    assert text.count(anchor) == 1
    p.write_text(text.replace(anchor, 'void cmd_info(Shard&, Op& op) {\n    std::string body = perfio_reparse_info();'))
    print(args.output)


if __name__ == '__main__': main()
