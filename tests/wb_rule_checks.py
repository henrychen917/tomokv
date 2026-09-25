#!/usr/bin/env python3
"""Serverless witnesses and clause-deletion controls; never launch tomokv.

emit writes isolated header overlays under build/. Mutants compile the same test
source against an altered production clause, not a different expected answer.
check accepts only exit 1 plus the specific assertion, never a crash or timeout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
POLICY = "src/core/wb_rule.h"
IO = "src/core/io_loop.h"

# name: (group, file, exact source, replacement, case, required assertion)
MUTANTS = {
    "fastpath": ("policy", POLICY, "if (n <= 1)", "if (false)", "fastpath", "fast path reads no staging or slots"),
    "staged-clause": ("policy", POLICY, "if (bytes >= kWbufInline) return false;\n    const auto head", "if (false) return false;\n    const auto head", "staged", "staged byte threshold"),
    "staged-source": ("policy", POLICY, "c.buffered_output_bytes()", "c.fill_buf().size()", "staged", "staged fill/send remainder/segments"),
    "submitted": ("policy", POLICY, "c.send_inflight() ? c.fill_buf().size() : c.buffered_output_bytes()", "c.buffered_output_bytes()", "submitted", "submitted bytes excluded"),
    "done-bytes": ("policy", POLICY, "bytes += reply_bytes(op);", "bytes += 0;", "bytes", "Done prefix byte threshold"),
    "spill": ("policy", POLICY, "return op.reply.size() +", "return 0 +", "bytes", "spill/direct/borrow including CRLF"),
    "direct": ("policy", POLICY, "code_bytes(op) : op.direct_len", "code_bytes(op) : 0", "bytes", "spill/direct/borrow including CRLF"),
    "borrow": ("policy", POLICY, "size_t(op.zc_len) + 2", "0", "bytes", "spill/direct/borrow including CRLF"),
    "crlf": ("policy", POLICY, "size_t(op.zc_len) + 2", "size_t(op.zc_len)", "bytes", "spill/direct/borrow including CRLF"),
    "no-sum": ("policy", POLICY, "bytes += reply_bytes(op);", "bytes = reply_bytes(op);", "bytes", "Done prefix bytes accumulate across slots"),
    "floor": ("policy", POLICY, "n * kPolicyFraction.num + kPolicyFraction.den - 1", "n * kPolicyFraction.num", "fraction", "ceil half for every n=1..64 and prefix"),
    "whole": ("policy", POLICY, "(n * kPolicyFraction.num + kPolicyFraction.den - 1) / kPolicyFraction.den", "n", "fraction", "ceil half for every n=1..64 and prefix"),
    "hole": ("policy", POLICY, "!= OpState::Done) break;", "!= OpState::Done) { ++prefix; continue; }", "holes", "first hole stops fraction and bytes"),
    "marker": ("policy", POLICY, "op.zc_ptr && op.zc_shard >= 0", "op.zc_ptr", "markers", "retire-state poison is not payload"),
    "code": ("policy", POLICY, "op.reply_code_ ? code_bytes(op)", "op.reply_code_ ? 0", "codes", "coded lengths match production encoder"),
    "relaxed": ("policy", POLICY, "std::memory_order_acquire", "std::memory_order_relaxed", "acquire", "Done load must acquire"),
    "pre-read": ("policy", POLICY,
                 "if (op.state.load(std::memory_order_acquire) != OpState::Done) break;\n        bytes += reply_bytes(op);",
                 "bytes += reply_bytes(op);\n        if (op.state.load(std::memory_order_acquire) != OpState::Done) break;",
                 "acquire", "reply field read before Done acquire"),
    "walk-tail": ("policy", POLICY, "while (prefix < threshold)", "while (prefix < n)", "acquire", "walk exits at successful fraction"),
    "budget": ("phase", POLICY, "const size_t serve_budget = ready_now", "const size_t serve_budget = 16", "fused-budget", "exact mode-specific budget"),
    "rotation": ("phase", POLICY, "loop.pending_serve_.push_back(c);\n                continue;", "/* removed rotation */\n                continue;", "fifo", "deferred rotation preserves order"),
    "head": ("phase", POLICY, "loop.pending_serve_.push_back(c);\n                continue;", "loop.pending_serve_.push_front(c);\n                continue;", "fifo", "younger eligible passes deferred head"),
    "pin": ("phase", POLICY, "loop.pending_serve_.push_back(c);\n                continue;", "c->set_serve_pending(false);\n                loop.pending_serve_.push_back(c);\n                continue;", "fifo", "deferred lifetime pins kept"),
    "capture": ("phase", POLICY, "visits < ready_now", "true", "capture", "callback cannot extend captured visit count"),
    "visit": ("phase", POLICY, "visits < ready_now", "visits <= ready_now", "fifo", "deferred rotation preserves order"),
    "dead": ("phase", POLICY, "!c->dead() && defer(*c)", "defer(*c)", "dead", "dead entry removed and unpinned"),
    "work": ("phase", POLICY, "if (!loop.pending_serve_.empty()) ++work; // deferred entries must get another phase", "if (false) ++work;", "progress", "deferral alone is positive work"),
    "split-policy": ("split-phase", POLICY, "!c->dead() && defer(*c)", "false", "split-policy", "2s uses exact composite fraction"),
    "split-local": ("split-phase", POLICY, "!c->dead() && defer(*c)", "false", "split-local", "2s reader capability shares composite writeback"),
    "split-budget": ("split-phase", POLICY, "const size_t serve_budget = ready_now", "const size_t serve_budget = 16", "split-budget", "exact mode-specific budget"),
    "split-aof": ("split-phase", IO, "if (!aof.reply_gate_ready(aof_gate_target_)) {\n                    aof.register_send_gate_wait(self_->id());\n                    return work;", "if (false) {\n                    aof.register_send_gate_wait(self_->id());\n                    return work;", "split-aof", "AOF refusal precedes composite selection"),
    "gather-policy": ("split-overlap", POLICY, "!client->dead() && defer(*client)", "false", "split-policy", "2s uses exact composite fraction"),
    "gather-rotation": ("split-overlap", POLICY, "loop.pending_serve_.push_back(client);", "/* removed rotation */", "split-fifo", "deferred rotation preserves order"),
    "gather-head": ("split-overlap", POLICY, "loop.pending_serve_.push_back(client);", "loop.pending_serve_.push_front(client);", "split-fifo", "younger eligible passes deferred head"),
    "gather-pin": ("split-overlap", POLICY, "loop.pending_serve_.push_back(client);", "client->set_serve_pending(false); loop.pending_serve_.push_back(client);", "split-fifo", "deferred lifetime pins kept"),
    "gather-capture": ("split-overlap", POLICY, "if (left == SIZE_MAX) left = loop.pending_serve_.size();", "left = loop.pending_serve_.size();", "split-capture-multi", "2s callback cannot extend captured chunks"),
    "gather-visit": ("split-overlap", POLICY, "left = loop.pending_serve_.size();", "left = loop.pending_serve_.size() + 1;", "split-fifo", "deferred rotation preserves order"),
    "gather-dead": ("split-overlap", POLICY, "!client->dead() && defer(*client)", "defer(*client)", "split-dead", "dead entry removed and unpinned"),
    "gather-work": ("split-overlap", IO, "if (!pending_serve_.empty() && captured_left != SIZE_MAX) ++work;", "if (false) ++work;", "split-progress", "deferral alone is positive work"),
    "gather-chunks": ("split-overlap", IO, "while (captured_left != SIZE_MAX && captured_left && !pending_serve_.empty())", "while (false)", "split-chunk", "2s captured pass crosses scratch bound"),
    "gather-aof": ("split-overlap", IO, "if (!aof.reply_gate_ready(aof_gate_target_)) {\n                aof.register_send_gate_wait(self_->id());\n                return 0;", "if (false) {\n                aof.register_send_gate_wait(self_->id());\n                return 0;", "split-aof", "AOF refusal precedes composite selection"),
    "split-ex": ("stages", "src/core/ex_loop.h",
                 "template <uint32_t BatchOps = kGenthreadExBatchOps,\n              bool IofusedPrivateQueue = false>\n    uint32_t drain_tasks(",
                 "template <uint32_t BatchOps = 2 * kGenthreadExBatchOps,\n              bool IofusedPrivateQueue = false>\n    uint32_t drain_tasks(",
                 "split-ex", "default split EX chunk remains 32"),
    "parse": ("stages", IO, "sig.ops - batch_start_ops >= BatchOps", "sig.ops - batch_start_ops >= 2 * BatchOps", "fused-parse", "unchanged parser quantum"),
}


def emit(name, output):
    _, file, old, new, _, _ = MUTANTS[name]
    output.mkdir(parents=True, exist_ok=True)
    # Only changed core headers are copied; every other path names the real source.
    core = output / "src/core"
    core.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "src").iterdir():
        dest = output / "src" / path.name
        if path.name != "core" and not dest.exists(): dest.symlink_to(path)
    for path in (ROOT / "src/core").iterdir():
        dest = core / path.name
        if dest.exists() or dest.is_symlink(): dest.unlink()
        if path == ROOT / file:
            source = path.read_text()
            assert source.count(old) == 1, (name, "mutation site changed", source.count(old))
            dest.write_text(source.replace(old, new))
        elif not dest.exists(): dest.symlink_to(path)


def check(group, build, controls=True):
    rows = []
    def run(binary, case, negative=None, extra=()):
        result = subprocess.run([str(binary), case, *extra], capture_output=True, text=True, timeout=45)
        expected = 1 if negative else 0
        marker = f"FAIL wb-rule {case}: {negative}" if negative else f"PASS wb-rule {case}"
        passed = result.returncode == expected and marker in result.stdout + result.stderr
        rows.append(dict(binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                         case=case, extra=extra, expected_exit=expected, exit=result.returncode,
                         required=marker, passed=passed, stdout=result.stdout, stderr=result.stderr))
        print(f"{'PASS' if passed else 'FAIL'} {group} {binary.name} {case} {' '.join(extra)}", flush=True)
        if not passed: print(result.stdout + result.stderr, flush=True)
    for ns in ("", "db0-"):
        if group == "policy":
            for case in ("fastpath", "fraction", "staged", "submitted", "bytes", "holes", "markers", "codes", "acquire"):
                run(build / f"wb-rule-{ns}unit", case)
        elif group == "phase":
            for extra in ((), ("r7",)):
                for case in ("fused-budget", "fastpath", "fifo", "capture", "dead", "progress"):
                    run(build / f"wb-rule-{ns}phase-unit", case, extra=extra)
        elif group == "stages":
            for case in ("split-ex", "split-ex-unmasked", "split-ex-timed", "fused-parse", "split-parse"):
                run(build / f"wb-rule-{ns}phase-unit", case)
        else:
            schedules = ((),) if group == "split-phase" else (("natural",), ("shallow",))
            for extra in schedules:
                for case in ("split-budget", "split-dead", "split-policy", "split-local", "split-fastpath",
                             "split-fifo", "split-capture", "split-progress", "split-chunk", "split-aof", "split-capture-multi"):
                    run(build / f"wb-rule-{ns}phase-unit", case, extra=extra)
            if group == "split-phase": run(build / f"wb-rule-{ns}phase-unit", "split-local-sweep")
    for name, (kind, _, _, _, case, assertion) in MUTANTS.items():
        if controls and kind == group:
            for extra in (("natural",), ("shallow",)) if group == "split-overlap" else ((),):
                run(build / "wb-rule-controls" / name / "unit", case, assertion, extra)
    # Shared PHASE 2 lifecycle controls must fail in physical split too.
    if controls and group == "split-phase":
        for name in ("rotation", "head", "pin", "capture", "visit", "dead", "work"):
            *_, case, assertion = MUTANTS[name]
            run(build / "wb-rule-controls" / name / "unit", "split-" + case, assertion)
    receipt = build / f"wb-rule-{group}{"" if controls else "-positive"}-proofs.json"
    receipt.write_text(json.dumps(rows, indent=2) + "\n")
    if not all(row["passed"] for row in rows): raise SystemExit(1)
    print(f"PASS wb-rule {group}: {len(rows)}/{len(rows)} strict outcomes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    emit_parser = sub.add_parser("emit")
    emit_parser.add_argument("name", choices=MUTANTS)
    emit_parser.add_argument("output", type=Path)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("group", choices=("policy", "phase", "stages", "split-phase", "split-overlap"))
    check_parser.add_argument("--build", type=Path, default=ROOT / "build")
    check_parser.add_argument("--positive-only", action="store_true", help="isolated study arm only; gate always includes controls")
    args = parser.parse_args()
    if args.command == "emit": emit(args.name, args.output)
    else: check(args.group, args.build.resolve(), not args.positive_only)
