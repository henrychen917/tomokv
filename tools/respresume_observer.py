#!/usr/bin/env python3
"""Make a throwaway incidence observer source tree; never edit production code.

Two independent witnesses, applied identically to PRE and POST trees:

1. perfio (the round-4 audit's NT4 counter, docs/respresume/audit/nt4-counters.patch):
   at every Incomplete multibulk, add the completed argv the parse attempt built.
   PRE discards that argv, so the next read re-parses it. POST subtracts only the
   argv that its frontier retained (exactly the audit definition of "re-parsed").
2. rr decode balance (mechanism-independent): every successful length-line decode
   (array count or bulk header, fast or slow decoder) adds one to rr_decoded_lines;
   every completed multibulk adds argc + 1 to rr_completed_lines. The difference is
   the number of length lines decoded more than once. It needs no knowledge of the
   frontier, so it also checks POST's retention against a different instrument.

Counters live on per-thread cache lines. They are not a throughput instrument.
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
struct alignas(64) RrDecodeCount {
    std::atomic<uint64_t> decoded{0}, completed{0};
};
inline RrDecodeCount rr_decode_counts[1024];
inline std::atomic<uint32_t> rr_decode_next{0};
inline RrDecodeCount& rr_decode_slot() {
    thread_local RrDecodeCount* slot =
        &rr_decode_counts[rr_decode_next.fetch_add(1, std::memory_order_relaxed) % 1024];
    return *slot;
}
inline std::string perfio_reparse_info() {
    uint64_t incomplete = 0, arguments = 0, decoded = 0, completed = 0;
    for (auto& c : perfio_reparse_counts) {
        incomplete += c.incomplete.load(std::memory_order_relaxed);
        arguments += c.arguments.load(std::memory_order_relaxed);
    }
    for (auto& c : rr_decode_counts) {
        decoded += c.decoded.load(std::memory_order_relaxed);
        completed += c.completed.load(std::memory_order_relaxed);
    }
    return "perfio_incomplete:" + std::to_string(incomplete) + "\\r\\n" +
           "perfio_reparsed_arguments:" + std::to_string(arguments) + "\\r\\n" +
           "rr_decoded_lines:" + std::to_string(decoded) + "\\r\\n" +
           "rr_completed_lines:" + std::to_string(completed) + "\\r\\n";
}
'''


def replace_once(text, old, new, what):
    assert text.count(old) == 1, (what, text.count(old))
    return text.replace(old, new)


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
    text = p.read_text()
    text = replace_once(text, '#include <cstdint>', '#include <cstdint>\n#include <atomic>\n#include <string>',
                        'includes')
    text = replace_once(text, 'enum class ParseResult { Ok, Incomplete, Error, Empty };',
                        'enum class ParseResult { Ok, Incomplete, Error, Empty };\n' + COUNTERS, 'counters')
    # Both decoders, identical text in PRE and POST: count each successful decode.
    text = replace_once(text, '            pos = i + 2;\n            out = v;\n            return ParseResult::Ok;',
                        '            pos = i + 2;\n            out = v;\n'
                        '            rr_decode_slot().decoded.fetch_add(1, std::memory_order_relaxed);\n'
                        '            return ParseResult::Ok;', 'parse_len_crlf')
    text = replace_once(text, '    pos = end + 2;\n    return ParseResult::Ok;',
                        '    pos = end + 2;\n'
                        '    rr_decode_slot().decoded.fetch_add(1, std::memory_order_relaxed);\n'
                        '    return ParseResult::Ok;', 'resp_length_slow')
    p.write_text(text)
    for filename in ('src/core/io_loop.h', 'src/core/reorder.cc'):
        p = args.output / filename
        text = p.read_text()
        anchor = 'if (pr == ParseResult::Incomplete) {\n'
        note = 'op->argc()'
        if args.post:
            # After suspend_multibulk, so the exact production validity tag participates.
            anchor = "if (pos < pass_rlen && pass_rbuf[pos] == '*') conn.suspend_multibulk();\n"
            note += ' - (conn.multibulk_pending() ? std::min(op->argc(), conn.multibulk_frontier().completed) : 0)'
        text = replace_once(text, anchor, anchor +
                            "                if (op->rbuf_off < pass_rlen && pass_rbuf[op->rbuf_off] == '*')\n" +
                            f'                    perfio_reparse_note(self_->id(), {note});\n', 'incomplete')
        anchor = 'if (pr == ParseResult::Empty) {\n'
        text = replace_once(text, anchor, anchor +
                            "                if (pass_rbuf[op->rbuf_off] == '*')\n"
                            '                    rr_decode_slot().completed.fetch_add(1, std::memory_order_relaxed);\n',
                            'empty')
        anchor = 'const uint32_t consumed = pos - conn.rpos();\n'
        text = replace_once(text, anchor, anchor +
                            "        if (pass_rbuf[op->rbuf_off] == '*')\n"
                            '            rr_decode_slot().completed.fetch_add(op->argc() + 1, std::memory_order_relaxed);\n',
                            'complete')
        p.write_text(text)
    p = args.output / 'src/cmd/t_server.cc'
    text = p.read_text()
    p.write_text(replace_once(text, 'void cmd_info(Shard&, Op& op) {\n    std::string body;',
                              'void cmd_info(Shard&, Op& op) {\n    std::string body = perfio_reparse_info();',
                              'info'))
    print(args.output)


if __name__ == '__main__': main()
