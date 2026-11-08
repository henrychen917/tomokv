#!/usr/bin/env python3
"""Replay the unchanged wire inventory through the production parser, without sockets.

PING/ECHO replies are formatted locally. This checks parser results, exact bytes,
fragmentation and the terminal Error result; live TCP close/ordering and Redis
differential validation still belong to respcompat.py and the maintainer's gate.
"""
import argparse
import json
from pathlib import Path
import subprocess

from respcompat import cases

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "src/net/resp.h"
#include <iostream>
#include <string>
static std::string unhex(const std::string& s) {
    std::string out;
    for (size_t i = 0; i < s.size(); i += 2)
        out += static_cast<char>(std::stoul(s.substr(i, 2), nullptr, 16));
    return out;
}
static std::string hex(const std::string& s) {
    if (s.empty()) return "-";
    const char* digits = "0123456789abcdef";
    std::string out;
    for (unsigned char c : s) { out += digits[c >> 4]; out += digits[c & 15]; }
    return out;
}
int main() {
    unsigned count; std::cin >> count;
    while (count--) {
        unsigned steps; std::cin >> steps;
        std::string buffer;
        uint32_t pos = 0;
        bool terminal = false;
        while (steps--) {
            bool supported = true;
            std::string input, reply; std::cin >> input;
            buffer += unhex(input);
            while (!terminal && pos < buffer.size()) {
                tomo::Op op; const char* error = nullptr;
                uint32_t next = pos;
                const auto result = tomo::resp_parse(buffer.data(), buffer.size(), next, op, &error);
                if (result == tomo::ParseResult::Incomplete) break;
                if (result == tomo::ParseResult::Error) {
                    if (op.reply.empty()) tomo::reply_err(op.reply, error ? error : "ERR protocol error");
                    reply.append(op.reply.data(), op.reply.size());
                    terminal = true;
                    break;
                }
                if (next <= pos) return 2;
                pos = next;
                if (result == tomo::ParseResult::Empty) continue;
                if (op.argc() == 1 && op.arg(0) == tomo::Slice("PING", 4)) tomo::reply_pong(op.reply);
                else if (op.argc() == 2 && op.arg(0) == tomo::Slice("ECHO", 4)) tomo::reply_bulk(op.reply, op.arg(1));
                else supported = false;
                reply.append(op.reply.data(), op.reply.size());
            }
            std::cout << terminal << ' ' << supported << ' ' << hex(reply) << '\n';
        }
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--include-root", type=Path, default=ROOT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source, binary = args.output / "replay.cc", args.output / "replay"
    source.write_text(SOURCE)
    subprocess.run(["g++", "-std=c++20", "-O2", "-g", "-Wall", "-Wextra", "-march=native",
                    "-I" + str(args.include_root), str(source), "-o", str(binary)], check=True)
    inventory = cases()
    inputs, expected = [str(len(inventory))], []
    for case in inventory:
        inputs.append(str(len(case.steps)))
        for step, (payload, reply) in enumerate(case.steps):
            inputs.append(payload.hex())
            expected.append((case.name, step, int(case.closes and step == len(case.steps) - 1), reply or b""))
    result = subprocess.run([str(binary.resolve())], input="\n".join(inputs) + "\n",
                            text=True, capture_output=True, check=True)
    lines = result.stdout.splitlines()
    assert len(lines) == len(expected), "replay must report every inventory step"
    failures = []
    for line, (name, step, terminal, reply) in zip(lines, expected):
        flag, supported, data = line.split()
        actual = b"" if data == "-" else bytes.fromhex(data)
        if supported != "1" or int(flag) != terminal or actual != reply:
            failures.append(dict(case=name, step=step, expected_terminal=terminal,
                                 actual_terminal=int(flag), unsupported_argv=supported != "1",
                                 expected=reply.hex(), actual=actual.hex()))
    receipt = dict(cases=len(inventory), steps=len(expected), failures=failures,
                   include_root=str(args.include_root.resolve()), sockets_opened=0,
                   checks_live_tcp_close=False, checks_redis_differential=False)
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"RESP serverless replay: {len(inventory)} cases, {len(expected)} steps, {len(failures)} failures")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
