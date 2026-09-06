#!/usr/bin/env python3
"""Graft (or remove) the ring-overflow counter. DIAGNOSTIC ONLY -- never committed into either arm.

The claim this lane makes is "sizing the ring to the ROB window makes capacity overflow
unreachable". A claim of NEVER is worth exactly the counter that could have caught it, so both arms
are measured with one. It is applied by patching whichever src/net/rob.h is in the tree, and the
three anchors it needs are textually identical in the base branch's header and in this lane's, so
the SAME patch instruments both arms and the two counts are comparable.

It is kept out of the measured binaries on purpose. PRE enters a conservative generation constantly
at high write ratios -- that is the defect -- so a shared relaxed counter on that path would land
in the arm it exists to describe, which is how a diagnostic ends up in its own measurement
(scratchpad/../tomokv-tripwire-armed-tax-incident). Rate, instr/op and IPC come from the clean
binaries; only the overflow count comes from these.

    ovf_patch.py apply|revert [root]
"""
import sys, os

ROB = "src/net/rob.h"
SRV = "src/cmd/t_server.cc"

ROB_GLOBAL = """
// ---- ringsize diagnostic (ovf_patch.py) --------------------------------------------------
// Entries into a conservative RYOW generation caused by the write ring FILLING. Relaxed: it is
// counted, never read, until INFO reads it once.
inline std::atomic<uint64_t> g_ringovf{0};
// ------------------------------------------------------------------------------------------
"""
ROB_INC = "        g_ringovf.fetch_add(1, std::memory_order_relaxed);   // ringsize diagnostic\n"
SRV_INFO = """        appendf(body, "read_local_write_ring_overflows:%llu\\r\\n",   // ringsize diagnostic
                static_cast<unsigned long long>(
                    g_ringovf.load(std::memory_order_relaxed)));
"""

NS = "namespace tomo {\n"
ENTER = "    void read_local_write_enter_overflow() {\n"
INFO = '        appendf(body,\n                "read_local_hits:%llu\\r\\n"'


def edit(path, pairs, mode):
    with open(path) as f:
        s = f.read()
    for anchor, add, where in pairs:
        if mode == "apply":
            if add in s:
                raise SystemExit(f"ovf_patch: {path} already carries the diagnostic")
            if s.count(anchor) != 1:
                raise SystemExit(f"ovf_patch: anchor appears {s.count(anchor)}x in {path}: {anchor!r}")
            s = s.replace(anchor, anchor + add if where == "after" else add + anchor, 1)
        else:
            if add not in s:
                raise SystemExit(f"ovf_patch: {path} does not carry the diagnostic")
            s = s.replace(add, "", 1)
    with open(path, "w") as f:
        f.write(s)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("apply", "revert"):
        raise SystemExit(__doc__)
    root = sys.argv[2] if len(sys.argv) > 2 else "."
    os.chdir(root)
    edit(ROB, [(NS, ROB_GLOBAL, "after"), (ENTER, ROB_INC, "after")], mode)
    edit(SRV, [(INFO, SRV_INFO, "before")], mode)
    print(f"ovf_patch: {mode}d in {os.getcwd()}")


main()
